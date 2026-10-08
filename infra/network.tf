resource "aws_vpc" "lab" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = local.name }
}

resource "aws_internet_gateway" "lab" {
  vpc_id = aws_vpc.lab.id
}

resource "aws_subnet" "public" {
  vpc_id            = aws_vpc.lab.id
  cidr_block        = "10.42.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
  tags              = { Name = "${local.name}-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.lab.id
}

resource "aws_route" "internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.lab.id
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_subnet" "private" {
  count             = var.private_network ? 1 : 0
  vpc_id            = aws_vpc.lab.id
  cidr_block        = "10.42.2.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
  tags              = { Name = "${local.name}-private" }
}

resource "aws_eip" "nat" {
  count  = var.private_network ? 1 : 0
  domain = "vpc"
}

resource "aws_nat_gateway" "lab" {
  count         = var.private_network ? 1 : 0
  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public.id
  depends_on    = [aws_internet_gateway.lab]
}

resource "aws_route_table" "private" {
  count  = var.private_network ? 1 : 0
  vpc_id = aws_vpc.lab.id
}

resource "aws_route" "nat" {
  count                  = var.private_network ? 1 : 0
  route_table_id         = aws_route_table.private[0].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.lab[0].id
}

resource "aws_route_table_association" "private" {
  count          = var.private_network ? 1 : 0
  subnet_id      = aws_subnet.private[0].id
  route_table_id = aws_route_table.private[0].id
}

resource "aws_security_group" "task" {
  name_prefix = "${local.name}-"
  description = "Laboratorio sin conexiones entrantes; salida HTTPS"
  vpc_id      = aws_vpc.lab.id
}

resource "aws_vpc_security_group_egress_rule" "https" {
  security_group_id = aws_security_group.task.id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}
