import json
import unittest
from unittest.mock import patch
from compliance import CASOS, seleccionar_casos
from test_lab_cli import lab, CONFIG, STATE


class SelectionTests(unittest.TestCase):
    def test_invalid_selection_rejected(self):
        for value in [[], {}, "finanzas", ["unknown"], [1], [CASOS[0].id, CASOS[0].id]]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                seleccionar_casos(value)

    def test_order_and_default(self):
        self.assertEqual(seleccionar_casos(), CASOS)
        self.assertEqual(seleccionar_casos([CASOS[2].id, CASOS[0].id]), (CASOS[0], CASOS[2]))

    def test_ecs_override_only_contains_selected_ids(self):
        with patch.object(lab, "aws", side_effect=[{}, {"tasks": [{"taskArn": "task"}]}]) as aws, \
             patch.object(lab, "wait_tasks", return_value=[{"containers": [{"exitCode": 0}]}]):
            lab.run(CONFIG, STATE, case_ids=[CASOS[2].id])
        args=aws.call_args.args
        overrides=json.loads(args[args.index("--overrides")+1])
        container=overrides["containerOverrides"][0]
        self.assertEqual(container["name"], "agents")
        self.assertEqual(json.loads(container["environment"][0]["value"]), [CASOS[2].id])

    def test_invalid_ids_never_contact_aws(self):
        with patch.object(lab, "aws") as aws, self.assertRaises(ValueError):
            lab.run(CONFIG, STATE, case_ids=["unknown"])
        aws.assert_not_called()
