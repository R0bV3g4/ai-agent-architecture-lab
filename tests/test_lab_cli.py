"""Pruebas locales del ciclo de vida; no se invoca AWS, Docker ni Terraform."""

import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("lab_cli", Path(__file__).resolve().parents[1] / "scripts/lab.py")
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)

CONFIG = {"aws_account_id": "123456789012", "aws_region": "us-east-1", "project_name": "crewai-lab"}
STATE = {
    "account_id": "123456789012", "region": "us-east-1",
    "cluster_arn": "arn:aws:ecs:us-east-1:123456789012:cluster/crewai-lab",
    "task_definition_arn": "arn:aws:ecs:us-east-1:123456789012:task-definition/crewai-lab:1",
    "image_tag": "test", "assign_public_ip": "DISABLED", "subnet_id": "subnet-test",
    "security_group_id": "sg-test",
}


class LifecycleTests(unittest.TestCase):
    def test_publish_preserves_secret_revision_and_rejects_unrelated_changes(self):
        state = {**STATE, "repository_url": "123456789012.dkr.ecr.us-east-1.amazonaws.com/crewai-lab"}
        saved = {"values": {"root_module": {"resources": [{"type": "aws_secretsmanager_secret_version", "values": {"secret_string_wo_version": 123}}]}}}
        for address, allowed in [("aws_ecs_task_definition.lab", True), ("aws_secretsmanager_secret_version.anthropic", False)]:
            with self.subTest(address=address):
                calls = []
                def terraform(*args, **kwargs):
                    calls.append(args)
                    if args[:2] == ("show", "-json"):
                        return json.dumps(saved if len(args) == 2 else {"resource_changes": [{"address": address, "change": {"actions": ["update"]}}]})
                    return ""
                with patch.object(lab, "require_commands"), patch.object(lab, "execute"), \
                     patch.object(lab, "aws", return_value="ecr-temporary"), patch.object(lab, "secret") as secret, \
                     patch.object(lab, "terraform", side_effect=terraform):
                    if allowed:
                        lab.publish(CONFIG, state)
                    else:
                        with self.assertRaises(lab.LabError):
                            lab.publish(CONFIG, state)
                secret.assert_not_called()
                self.assertEqual(any(c[0] == "apply" for c in calls), allowed)
                plan = next(c for c in calls if c[0] == "plan")
                self.assertIn("-var=secret_revision=123", plan)

    def test_secrets_are_not_inherited_by_build_or_aws_processes(self):
        with patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "sensitive-a", "DD_API_KEY": "sensitive-dd",
            "TF_VAR_anthropic_api_key": "sensitive-c", "AWS_PROFILE": "lab-profile",
        }):
            env = lab.environment()
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("DD_API_KEY", env)
        self.assertNotIn("TF_VAR_anthropic_api_key", env)
        self.assertEqual(env["AWS_PROFILE"], "lab-profile")

    def test_wrong_aws_account_aborts(self):
        with patch.object(lab, "aws", return_value={"Account": "999999999999"}):
            with self.assertRaises(lab.LabError):
                lab.check_account(CONFIG)

    def test_changed_region_cannot_destroy_old_state(self):
        with self.assertRaises(lab.LabError):
            lab.check_state({**CONFIG, "aws_region": "us-west-2"}, STATE)

    def test_destroy_waits_for_running_tasks_before_terraform(self):
        calls = []

        def fake_aws(config, *args, **kwargs):
            calls.append(args[1])
            return {"taskArns": ["task-a", "task-b"]} if args[1] == "list-tasks" else {}

        with patch.object(lab, "aws", side_effect=fake_aws), \
             patch.object(lab, "wait_tasks", side_effect=lambda *args: calls.append("wait")), \
             patch.object(lab, "terraform", side_effect=lambda *args: calls.append(args[0])):
            lab.down(CONFIG, STATE)
        self.assertEqual(calls, ["list-tasks", "stop-task", "stop-task", "wait", "destroy"])

    def test_destroy_does_not_proceed_if_task_stop_fails(self):
        with patch.object(lab, "aws", side_effect=[{"taskArns": ["task-a"]}, lab.LabError("stop failed")]), \
             patch.object(lab, "terraform") as terraform:
            with self.assertRaises(lab.LabError):
                lab.down(CONFIG, STATE)
            terraform.assert_not_called()

    def test_run_checks_container_exit_code(self):
        with patch.object(lab, "aws", side_effect=[{}, {"tasks": [{"taskArn": "task-a"}]}]), \
             patch.object(lab, "wait_tasks", return_value=[{
                 "lastStatus": "STOPPED", "stoppedReason": "Essential container exited",
                 "containers": [{"exitCode": 1}],
             }]):
            with self.assertRaises(lab.LabError):
                lab.run(CONFIG, STATE)

    def test_ecs_launch_failure_is_not_success(self):
        with patch.object(lab, "aws", side_effect=[{}, {"failures": [{"reason": "RESOURCE"}]}]), \
             patch.object(lab, "wait_tasks") as wait:
            with self.assertRaises(lab.LabError):
                lab.run(CONFIG, STATE)
            wait.assert_not_called()

    def test_network_settings_follow_terraform_outputs(self):
        network = json.loads(lab.network_configuration(STATE))["awsvpcConfiguration"]
        self.assertEqual(network["assignPublicIp"], "DISABLED")
        self.assertEqual(network["subnets"], ["subnet-test"])

    def test_wait_retries_eventually_consistent_task_lookup(self):
        done = {"taskArn": "task-a", "lastStatus": "STOPPED"}
        with patch.object(lab, "aws", side_effect=[
            {"failures": [{"reason": "MISSING"}], "tasks": []},
            {"tasks": [done]},
        ]), patch.object(lab.time, "sleep") as sleep:
            self.assertEqual(lab.wait_tasks(CONFIG, "cluster-a", ["task-a"]), [done])
            sleep.assert_called_once_with(10)

    def test_up_builds_before_apply_then_pushes_without_secret_arguments(self):
        calls = []
        state = {**STATE, "repository_url": "123456789012.dkr.ecr.us-east-1.amazonaws.com/crewai-lab"}

        def execute(args, **kwargs):
            calls.append((args, kwargs))
            return ""

        def terraform(*args, **kwargs):
            calls.append((["terraform", *args], kwargs))
            return ""

        with patch.object(lab, "require_commands"), patch.object(lab, "initialize"), \
             patch.object(lab, "secret", return_value="test-api-secret"), \
             patch.object(lab, "outputs", side_effect=[{}, state]), \
             patch.object(lab, "execute", side_effect=execute), \
             patch.object(lab, "terraform", side_effect=terraform), \
             patch.object(lab, "aws", return_value="temporary-ecr-password"):
            lab.up({**CONFIG, "observability_provider": "datadog"})
        commands = [args[:2] for args, _ in calls]
        self.assertLess(commands.index(["docker", "build"]), commands.index(["terraform", "apply"]))
        self.assertLess(commands.index(["terraform", "apply"]), commands.index(["docker", "push"]))
        for args, _ in calls:
            self.assertNotIn("test-api-secret", " ".join(args))
            self.assertNotIn("temporary-ecr-password", " ".join(args))
        login_kwargs = next(kwargs for args, kwargs in calls if args[:2] == ["docker", "login"])
        self.assertEqual(login_kwargs["input_text"], "temporary-ecr-password\n")
        apply_kwargs = next(kwargs for args, kwargs in calls if args[:2] == ["terraform", "apply"])
        self.assertEqual(apply_kwargs["env"]["TF_VAR_datadog_api_key"], "test-api-secret")


if __name__ == "__main__":
    unittest.main()
