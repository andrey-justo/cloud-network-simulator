"""Independent, finite structural and runtime contracts for the network benchmark.

Structural acceptance is not a proof of deployment or network reachability.
Unsupported ARM expressions fail closed rather than being interpreted as literals.
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

NETWORK = "Microsoft.Network/"


@dataclass(frozen=True)
class Reference:
    resource_id: str
    path: str = ""


class ArmEvaluationError(ValueError):
    pass


def _arguments(text: str) -> list[str]:
    parts: list[str] = []
    start = depth = 0
    quoted = False
    index = 0
    while index < len(text):
        character = text[index]
        if character == "'":
            if quoted and index + 1 < len(text) and text[index + 1] == "'":
                index += 2
                continue
            quoted = not quoted
        elif not quoted:
            depth += character in "(["
            depth -= character in ")]"
            if character == "," and depth == 0:
                parts.append(text[start:index].strip())
                start = index + 1
        index += 1
    if quoted or depth:
        raise ArmEvaluationError("Unbalanced ARM expression.")
    if text[start:].strip():
        parts.append(text[start:].strip())
    return parts


class ArmDocument:
    def __init__(
        self, template: dict[str, Any], parameters: dict[str, Any] | None = None
    ):
        self.template = template
        self.parameters = parameters or {}
        self.resources: list[dict[str, Any]] = []
        raw_resources = template.get("resources")
        if not isinstance(raw_resources, list):
            raise ArmEvaluationError(
                "Only resource-group ARM templates with a resources array are supported."
            )
        for resource in raw_resources:
            self._collect(resource)

    def _collect(
        self, resource: Any, parent_type: str = "", parent_name: str = ""
    ) -> None:
        if (
            not isinstance(resource, dict)
            or "copy" in resource
            or resource.get("condition", True) is not True
        ):
            raise ArmEvaluationError(
                "Conditional/copied resources require a resolved deployment view."
            )
        item = dict(resource)
        resource_type = item.get("type", "")
        name = self.resolve(item.get("name"))
        if not isinstance(resource_type, str) or not isinstance(name, str):
            raise ArmEvaluationError("Resource type and name must resolve to strings.")
        if parent_type and not resource_type.lower().startswith("microsoft."):
            resource_type = f"{parent_type}/{resource_type}"
            name = f"{parent_name}/{name}"
        item.update(type=resource_type, name=name)
        self.resources.append(item)
        for child in resource.get("resources", []):
            self._collect(child, resource_type, name)
        if resource_type.lower() == f"{NETWORK}virtualNetworks".lower():
            for subnet in resource.get("properties", {}).get("subnets", []):
                self._collect(
                    {**subnet, "type": "subnets"},
                    resource_type,
                    name,
                )

    def resolve(self, value: Any, stack: tuple[str, ...] = ()) -> Any:
        if isinstance(value, str) and value.startswith("[") and value.endswith("]"):
            return self._expression(value[1:-1], stack)
        if isinstance(value, list):
            return [self.resolve(item, stack) for item in value]
        if isinstance(value, dict):
            return {key: self.resolve(item, stack) for key, item in value.items()}
        return value

    def _expression(self, text: str, stack: tuple[str, ...]) -> Any:
        text = text.strip()
        if text.startswith("'") and text.endswith("'"):
            return text[1:-1].replace("''", "'")
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        if text.lower() in ("true", "false"):
            return text.lower() == "true"
        match = re.match(r"([A-Za-z]+)\(", text)
        if not match:
            raise ArmEvaluationError(f"Unsupported ARM expression: {text}")
        depth, quoted, end = 1, False, match.end()
        while end < len(text):
            character = text[end]
            if character == "'":
                if quoted and end + 1 < len(text) and text[end + 1] == "'":
                    end += 2
                    continue
                quoted = not quoted
            elif not quoted:
                depth += character == "("
                depth -= character == ")"
                if depth == 0:
                    break
            end += 1
        if depth:
            raise ArmEvaluationError("Unbalanced ARM function.")
        arguments = [
            self._expression(item, stack)
            for item in _arguments(text[match.end() : end])
        ]
        function = match[1].lower()
        if function in ("parameters", "variables"):
            if len(arguments) != 1 or not isinstance(arguments[0], str):
                raise ArmEvaluationError("Invalid ARM variable/parameter reference.")
            key = arguments[0]
            token = f"{function}:{key}"
            if token in stack:
                raise ArmEvaluationError("Cyclic ARM variable/parameter reference.")
            if function == "variables":
                raw = self.template.get("variables", {}).get(key)
            else:
                raw = self.parameters.get(
                    key,
                    self.template.get("parameters", {})
                    .get(key, {})
                    .get("defaultValue"),
                )
                if isinstance(raw, dict) and "value" in raw:
                    raw = raw["value"]
            if raw is None:
                raise ArmEvaluationError(f"Missing ARM value: {token}")
            result = self.resolve(raw, (*stack, token))
        elif function == "resourceid":
            if (
                not arguments
                or not isinstance(arguments[0], str)
                or not arguments[0].startswith("Microsoft.")
            ):
                raise ArmEvaluationError(
                    "Only same-resource-group resourceId references are supported."
                )
            result = self.resource_id(
                arguments[0], "/".join(str(item) for item in arguments[1:])
            )
        elif function == "reference":
            if not arguments or not isinstance(arguments[0], str):
                raise ArmEvaluationError("Invalid reference().")
            result = Reference(arguments[0])
        elif function == "concat":
            result = "".join(str(item) for item in arguments)
        elif function == "format":
            result = str(arguments[0]).format(*arguments[1:])
        elif function in ("tolower", "toupper"):
            result = (
                str(arguments[0]).lower()
                if function == "tolower"
                else str(arguments[0]).upper()
            )
        elif function == "resourcegroup" and not arguments:
            result = {
                "location": "benchmark-location",
                "name": "benchmark-group",
                "id": "/resourceGroups/benchmark-group",
            }
        else:
            raise ArmEvaluationError(f"Unsupported ARM function: {function}")
        suffix = text[end + 1 :]
        if suffix:
            if isinstance(result, Reference):
                return Reference(result.resource_id, suffix.lstrip("."))
            for part in re.findall(r"\.([A-Za-z_]\w*)|\[(\d+)\]", suffix):
                try:
                    result = result[part[0]] if part[0] else result[int(part[1])]
                except (KeyError, TypeError, IndexError) as error:
                    raise ArmEvaluationError("Invalid ARM property access.") from error
            if (
                "".join(
                    f".{a}" if a else f"[{b}]"
                    for a, b in re.findall(r"\.([A-Za-z_]\w*)|\[(\d+)\]", suffix)
                )
                != suffix
            ):
                raise ArmEvaluationError("Unsupported ARM property access.")
        return result

    @staticmethod
    def resource_id(resource_type: str, name: str) -> str:
        types, names = resource_type.split("/"), name.split("/")
        if len(types) != len(names) + 1:
            raise ArmEvaluationError("Invalid resource ID segments.")
        return "/".join(
            [types[0], *(part for pair in zip(types[1:], names) for part in pair)]
        ).lower()

    def find(self, resource_type: str, name: str) -> dict[str, Any]:
        matches = [
            item
            for item in self.resources
            if item["type"].lower() == resource_type.lower()
            and item["name"].lower() == name.lower()
        ]
        if len(matches) != 1:
            raise ArmEvaluationError(
                f"Expected exactly one {resource_type}/{name}; found {len(matches)}."
            )
        return matches[0]


def _rule(
    name: str,
    source: str,
    port: int,
    priority: int,
    *,
    direction: str = "Inbound",
    access: str = "Allow",
    destination: str = "*",
) -> dict[str, Any]:
    return {
        "name": name,
        "properties": {
            "priority": priority,
            "direction": direction,
            "access": access,
            "protocol": "Tcp",
            "sourcePortRange": "*",
            "sourceAddressPrefix": source,
            "destinationPortRange": str(port),
            "destinationAddressPrefix": destination,
        },
    }


def _deny(direction: str = "Inbound") -> dict[str, Any]:
    return {
        "name": f"deny-{direction.lower()}",
        "properties": {
            "priority": 4000,
            "direction": direction,
            "access": "Deny",
            "protocol": "*",
            "sourcePortRange": "*",
            "destinationPortRange": "*",
            "sourceAddressPrefix": "*",
            "destinationAddressPrefix": "*",
        },
    }


def scenario_contract(scenario_id: str) -> dict[str, Any]:
    if scenario_id not in {f"NET-{number:02}" for number in range(1, 11)}:
        raise ValueError(f"No study contract for {scenario_id}.")
    resources: dict[str, Any] = {}
    runtime: list[dict[str, Any]] = []

    def add(
        role: str,
        resource_type: str,
        name: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        resources[role] = {
            "type": resource_type,
            "name": name,
            "properties": properties or {},
        }

    def ref(role: str) -> dict[str, str]:
        return {"$resource": role}

    def tcp(
        key: str, source: str, destination: str, port: int, expected: bool = True
    ) -> None:
        runtime.append(
            {
                "id": key,
                "kind": "tcp",
                "source": source,
                "destination": destination,
                "port": port,
                "expected": expected,
            }
        )

    def vnet(role: str, name: str, prefix: str, subnets: list[tuple[str, str]]) -> None:
        add(
            role,
            NETWORK + "virtualNetworks",
            name,
            {"addressSpace": {"addressPrefixes": [prefix]}},
        )
        for subnet_name, cidr in subnets:
            add(
                f"{role}-{subnet_name}",
                NETWORK + "virtualNetworks/subnets",
                f"{name}/{subnet_name}",
                {"addressPrefix": cidr},
            )

    if scenario_id in ("NET-01", "NET-02", "NET-03", "NET-08", "NET-10"):
        subnets = [("web", "10.1.1.0/24")]
        if scenario_id != "NET-01":
            subnets += [("app", "10.1.2.0/24"), ("data", "10.1.3.0/24")]
        vnet("vnet", "benchmark-vnet", "10.1.0.0/16", subnets)
        tcp("web-local", "web", "web-peer", 8080)
        if scenario_id == "NET-02":
            for source, destination in (
                ("web", "app"),
                ("app", "data"),
                ("data", "web"),
            ):
                tcp(f"{source}-{destination}", source, destination, 8080)
        if scenario_id in ("NET-03", "NET-08", "NET-10"):
            database_port = 5432 if scenario_id == "NET-03" else 1433
            for tier, allows in {
                "web": [
                    _rule("http", "Internet", 80, 100),
                    _rule("https", "Internet", 443, 110),
                ],
                "app": [_rule("from-web", "10.1.1.0/24", 8080, 100)],
                "data": [_rule("from-app", "10.1.2.0/24", database_port, 100)],
            }.items():
                rules = [*allows, _deny()]
                if tier == "data" and scenario_id in ("NET-08", "NET-10"):
                    rules.append(_deny("Outbound"))
                add(
                    f"nsg-{tier}",
                    NETWORK + "networkSecurityGroups",
                    f"benchmark-{tier}",
                    {"securityRules": {"$exact": rules}},
                )
                resources[f"vnet-{tier}"]["properties"]["networkSecurityGroup"] = {
                    "id": ref(f"nsg-{tier}")
                }
            runtime.clear()
            for source, destination, port, expected in (
                ("external", "web", 80, True),
                ("external", "web", 443, True),
                ("external", "app", 8080, False),
                ("external", "data", database_port, False),
                ("web", "app", 8080, True),
                ("web", "data", database_port, False),
                ("app", "data", database_port, True),
                ("app", "web", 8080, False),
            ):
                target = (
                    "web-public"
                    if scenario_id == "NET-03"
                    and source == "external"
                    and destination == "web"
                    else destination
                )
                tcp(f"{source}-{destination}-{port}", source, target, port, expected)
        if scenario_id in ("NET-08", "NET-10"):

            def gateway_part(collection: str, name: str) -> dict[str, str]:
                return {
                    "$subresource": "gateway",
                    "collection": collection,
                    "name": name,
                }

            add(
                "gateway-subnet",
                NETWORK + "virtualNetworks/subnets",
                "benchmark-vnet/gateway",
                {"addressPrefix": "10.1.4.0/24"},
            )
            # The gateway is the only public entry point in these scenarios.
            resources["nsg-web"]["properties"]["securityRules"]["$exact"] = [
                _rule("from-gateway", "10.1.4.0/24", 80, 100),
                _deny(),
            ]
            add(
                "gateway-ip",
                NETWORK + "publicIPAddresses",
                "benchmark-gateway-ip",
                {"publicIPAllocationMethod": "Static"},
            )
            add(
                "gateway",
                NETWORK + "applicationGateways",
                "benchmark-gateway",
                {
                    "sku": {
                        "name": "WAF_v2" if scenario_id == "NET-10" else "Standard_v2"
                    },
                    "autoscaleConfiguration": {"minCapacity": 0, "maxCapacity": 2},
                    "gatewayIPConfigurations": {
                        "$exact": [
                            {
                                "name": "gateway",
                                "properties": {"subnet": {"id": ref("gateway-subnet")}},
                            }
                        ]
                    },
                    "frontendIPConfigurations": {
                        "$exact": [
                            {
                                "name": "public",
                                "properties": {
                                    "publicIPAddress": {"id": ref("gateway-ip")}
                                },
                            }
                        ]
                    },
                    "frontendPorts": {
                        "$exact": [{"name": "http", "properties": {"port": 80}}]
                    },
                    "backendHttpSettingsCollection": {
                        "$exact": [
                            {
                                "name": "web-settings",
                                "properties": {
                                    "port": 80,
                                    "protocol": "Http",
                                    "cookieBasedAffinity": "Disabled",
                                    "requestTimeout": 30,
                                },
                            }
                        ]
                    },
                    "backendAddressPools": {
                        "$exact": [
                            {
                                "name": "web",
                                "properties": {
                                    "backendAddresses": [{"ipAddress": "10.1.1.4"}]
                                },
                            }
                        ]
                    },
                    "httpListeners": {
                        "$exact": [
                            {
                                "name": "http",
                                "properties": {
                                    "frontendIPConfiguration": {
                                        "id": gateway_part(
                                            "frontendIPConfigurations", "public"
                                        )
                                    },
                                    "frontendPort": {
                                        "id": gateway_part("frontendPorts", "http")
                                    },
                                    "protocol": "Http",
                                },
                            }
                        ]
                    },
                    "requestRoutingRules": {
                        "$exact": [
                            {
                                "name": "web",
                                "properties": {
                                    "priority": 100,
                                    "ruleType": "Basic",
                                    "httpListener": {
                                        "id": gateway_part("httpListeners", "http")
                                    },
                                    "backendAddressPool": {
                                        "id": gateway_part("backendAddressPools", "web")
                                    },
                                    "backendHttpSettings": {
                                        "id": gateway_part(
                                            "backendHttpSettingsCollection",
                                            "web-settings",
                                        )
                                    },
                                },
                            }
                        ]
                    },
                },
            )
            runtime[:] = [item for item in runtime if item["source"] != "external"]
            tcp("external-gateway", "external", "gateway", 80)
            tcp("external-web-blocked", "external", "web", 80, False)
            runtime.append(
                {
                    "id": "external-gateway-http",
                    "kind": "http",
                    "source": "external",
                    "destination": "gateway",
                    "port": 80,
                    "expected": True,
                }
            )
            tcp("data-internet", "data", "internet", 443, False)
        if scenario_id == "NET-10":
            resources["gateway"]["properties"][
                "webApplicationFirewallConfiguration"
            ] = {
                "enabled": True,
                "firewallMode": "Prevention",
                "ruleSetType": "OWASP",
                "ruleSetVersion": "3.2",
            }
            add(
                "sql",
                "Microsoft.Sql/servers",
                "benchmark-sql-local",
                {
                    "publicNetworkAccess": "Disabled",
                    "minimalTlsVersion": "1.2",
                    "administratorLogin": {"$parameter": "sqlAdministratorLogin"},
                    "administratorLoginPassword": {
                        "$parameter": "sqlAdministratorPassword"
                    },
                },
            )
            add(
                "database",
                "Microsoft.Sql/servers/databases",
                "benchmark-sql-local/benchmark-db",
            )
            add(
                "audit",
                "Microsoft.Sql/servers/auditingSettings",
                "benchmark-sql-local/default",
                {
                    "state": "Enabled",
                    "storageEndpoint": {
                        "$parameter": "auditStorageEndpoint",
                        "$https_url": True,
                    },
                    "storageAccountAccessKey": {"$parameter": "auditStorageKey"},
                },
            )
            add(
                "private-endpoint",
                NETWORK + "privateEndpoints",
                "benchmark-sql-pe",
                {
                    "subnet": {"id": ref("vnet-data")},
                    "privateLinkServiceConnections": [
                        {
                            "properties": {
                                "privateLinkServiceId": ref("sql"),
                                "groupIds": ["sqlServer"],
                            }
                        }
                    ],
                },
            )
            resources["vnet-data"]["properties"]["privateEndpointNetworkPolicies"] = (
                "Enabled"
            )
            add("dns", NETWORK + "privateDnsZones", "privatelink.database.windows.net")
            add(
                "dns-link",
                NETWORK + "privateDnsZones/virtualNetworkLinks",
                "privatelink.database.windows.net/benchmark-vnet",
                {
                    "virtualNetwork": {"id": ref("vnet")},
                    "registrationEnabled": False,
                },
            )
            add(
                "dns-group",
                NETWORK + "privateEndpoints/privateDnsZoneGroups",
                "benchmark-sql-pe/default",
                {
                    "privateDnsZoneConfigs": [
                        {"properties": {"privateDnsZoneId": ref("dns")}}
                    ],
                },
            )
            runtime.append(
                {
                    "id": "sql-private-dns",
                    "kind": "dns_private",
                    "source": "app",
                    "destination": "sql",
                }
            )
            tcp("app-private-sql", "app", "sql", 1433)
            runtime.append(
                {
                    "id": "sql-public-access-disabled",
                    "kind": "public_access_disabled",
                    "source": "control-plane",
                    "destination": "sql",
                }
            )
    elif scenario_id in ("NET-04", "NET-05"):
        vnet("vnet", "benchmark-vnet", "10.1.0.0/16", [("workload", "10.1.1.0/24")])
        if scenario_id == "NET-04":
            add(
                "nat-ip",
                NETWORK + "publicIPAddresses",
                "benchmark-nat-ip",
                {"publicIPAllocationMethod": "Static"},
            )
            add(
                "nat",
                NETWORK + "natGateways",
                "benchmark-nat",
                {"publicIpAddresses": [{"id": ref("nat-ip")}]},
            )
            resources["vnet-workload"]["properties"]["natGateway"] = {"id": ref("nat")}
            runtime.append(
                {
                    "id": "nat-egress-ip",
                    "kind": "egress_ip",
                    "source": "workload",
                    "destination": "ip-echo",
                }
            )
            tcp("external-workload", "external", "workload", 8080, False)
        else:
            add(
                "routes",
                NETWORK + "routeTables",
                "benchmark-routes",
                {
                    "routes": {
                        "$exact": [
                            {
                                "name": "discard",
                                "properties": {
                                    "addressPrefix": "10.250.0.0/16",
                                    "nextHopType": "None",
                                },
                            },
                        ]
                    }
                },
            )
            resources["vnet-workload"]["properties"]["routeTable"] = {
                "id": ref("routes")
            }
            runtime.append(
                {
                    "id": "discard-next-hop",
                    "kind": "route",
                    "source": "workload",
                    "destination": "discard",
                    "expected_next_hop_type": "None",
                }
            )
            tcp("discard-flow", "workload", "discard", 443, False)
    else:
        for role, number in (("hub", 10), ("spoke1", 20), ("spoke2", 30)):
            subnets = [("workload", f"10.{number}.1.0/24")]
            if scenario_id == "NET-07" and role == "hub":
                subnets.append(("AzureFirewallSubnet", "10.10.0.0/26"))
            vnet(role, f"benchmark-{role}", f"10.{number}.0.0/16", subnets)
        for spoke in ("spoke1", "spoke2"):
            for source, target in (("hub", spoke), (spoke, "hub")):
                add(
                    f"peer-{source}-{target}",
                    NETWORK + "virtualNetworks/virtualNetworkPeerings",
                    f"benchmark-{source}/to-{target}",
                    {
                        "remoteVirtualNetwork": {"id": ref(target)},
                        "allowVirtualNetworkAccess": True,
                        "allowForwardedTraffic": scenario_id == "NET-07",
                        "allowGatewayTransit": False,
                        "useRemoteGateways": False,
                    },
                )
            tcp(f"hub-{spoke}", "hub", spoke, 8080)
            tcp(f"{spoke}-hub", spoke, "hub", 8080)
        tcp("spoke1-spoke2", "spoke1", "spoke2", 8080, False)
        if scenario_id == "NET-07":
            add(
                "firewall-ip",
                NETWORK + "publicIPAddresses",
                "benchmark-firewall-ip",
                {"publicIPAllocationMethod": "Static"},
            )
            add(
                "firewall",
                NETWORK + "azureFirewalls",
                "benchmark-firewall",
                {
                    "sku": {"name": "AZFW_VNet", "tier": "Standard"},
                    "ipConfigurations": [
                        {
                            "properties": {
                                "subnet": {"id": ref("hub-AzureFirewallSubnet")},
                                "publicIPAddress": {"id": ref("firewall-ip")},
                            }
                        }
                    ],
                    "networkRuleCollections": {
                        "$exact": [
                            {
                                "name": "https-egress",
                                "properties": {
                                    "priority": 100,
                                    "action": {"type": "Allow"},
                                    "rules": {
                                        "$exact": [
                                            {
                                                "name": "https",
                                                "protocols": ["TCP"],
                                                "sourceAddresses": [
                                                    "10.20.0.0/16",
                                                    "10.30.0.0/16",
                                                ],
                                                "destinationAddresses": ["*"],
                                                "destinationPorts": ["443"],
                                            }
                                        ]
                                    },
                                },
                            }
                        ]
                    },
                },
            )
            for spoke in ("spoke1", "spoke2"):
                add(
                    f"routes-{spoke}",
                    NETWORK + "routeTables",
                    f"benchmark-{spoke}-routes",
                    {
                        "routes": {
                            "$exact": [
                                {
                                    "name": "default-firewall",
                                    "properties": {
                                        "addressPrefix": "0.0.0.0/0",
                                        "nextHopType": "VirtualAppliance",
                                        "nextHopIpAddress": {
                                            "$reference": "firewall",
                                            "path": "ipConfigurations[0].properties.privateIPAddress",
                                        },
                                    },
                                },
                            ]
                        }
                    },
                )
                resources[f"{spoke}-workload"]["properties"]["routeTable"] = {
                    "id": ref(f"routes-{spoke}")
                }
                runtime += [
                    {
                        "id": f"{spoke}-firewall-route",
                        "kind": "route",
                        "source": spoke,
                        "destination": "internet",
                        "expected_next_hop_type": "VirtualAppliance",
                    },
                    {
                        "id": f"{spoke}-egress-ip",
                        "kind": "egress_ip",
                        "source": spoke,
                        "destination": "ip-echo",
                    },
                ]
                tcp(f"{spoke}-https", spoke, "internet", 443)
                tcp(f"{spoke}-http-blocked", spoke, "internet", 80, False)
        if scenario_id == "NET-09":
            add(
                "bus",
                "Microsoft.ServiceBus/namespaces",
                "benchmark-bus-local",
                {"publicNetworkAccess": "Disabled", "minimumTlsVersion": "1.2"},
            )
            resources["bus"]["sku"] = {
                "name": "Premium",
                "tier": "Premium",
                "capacity": 1,
            }
            add(
                "private-endpoint",
                NETWORK + "privateEndpoints",
                "benchmark-bus-pe",
                {
                    "subnet": {"id": ref("hub-workload")},
                    "privateLinkServiceConnections": [
                        {
                            "properties": {
                                "privateLinkServiceId": ref("bus"),
                                "groupIds": ["namespace"],
                            }
                        }
                    ],
                },
            )
            add(
                "dns", NETWORK + "privateDnsZones", "privatelink.servicebus.windows.net"
            )
            for role in ("hub", "spoke1", "spoke2"):
                add(
                    f"dns-{role}",
                    NETWORK + "privateDnsZones/virtualNetworkLinks",
                    f"privatelink.servicebus.windows.net/{role}",
                    {
                        "virtualNetwork": {"id": ref(role)},
                        "registrationEnabled": False,
                    },
                )
            add(
                "dns-group",
                NETWORK + "privateEndpoints/privateDnsZoneGroups",
                "benchmark-bus-pe/default",
                {
                    "privateDnsZoneConfigs": [
                        {"properties": {"privateDnsZoneId": ref("dns")}}
                    ],
                },
            )
            for spoke in ("spoke1", "spoke2"):
                runtime.append(
                    {
                        "id": f"{spoke}-bus-dns",
                        "kind": "dns_private",
                        "source": spoke,
                        "destination": "bus",
                    }
                )
                tcp(f"{spoke}-bus", spoke, "bus", 5671)
            runtime.append(
                {
                    "id": "bus-public-access-disabled",
                    "kind": "public_access_disabled",
                    "source": "control-plane",
                    "destination": "bus",
                }
            )
    return {
        "version": 1,
        "scenario_id": scenario_id,
        "resources": resources,
        "parameters": {
            "studySuffix": {"type": "string", "defaultValue": "local"},
            **(
                {
                    "sqlAdministratorLogin": {
                        "type": "string",
                        "defaultValue": "studyadmin",
                    },
                    "sqlAdministratorPassword": {"type": "secureString"},
                    "auditStorageEndpoint": {
                        "type": "string",
                        "defaultValue": "https://benchmarkauditlocal.blob.core.windows.net",
                    },
                    "auditStorageKey": {"type": "secureString"},
                }
                if scenario_id == "NET-10"
                else {}
            ),
        },
        "runtime_checks": runtime,
        "scope": "resourceGroup",
        "requirements": [
            "Use exactly the declared benchmark resource names and required properties.",
            "Every VNet must have a nonempty Experiment tag.",
            "No workload NIC public IPs, except the NET-03 web test fixture; NET-08/10 use only Application Gateway for public ingress.",
            "Use Standard SKU for public IP resources; no undeclared VNets or subnets.",
            "Inline or child subnet declarations are both supported; avoid ARM resource copy loops.",
            "Runtime probe fixtures are provisioned by the evaluator, not the candidate.",
            "For NET-08/10 the web HTTP probe fixture is assigned 10.1.1.4; configure the gateway backend pool for this address.",
            "Declare param studySuffix string = 'local'; use it as the suffix of SQL server and Service Bus namespace names instead of hardcoding 'local'.",
            "Do not include deploymentScripts, role assignments, nested deployments, VM extensions, or cross-scope resources.",
        ],
    }


def _matches(
    actual: Any, expected: Any, document: ArmDocument, resources: dict[str, Any]
) -> bool:
    if isinstance(expected, dict) and "$parameter" in expected:
        matched = (
            isinstance(actual, str)
            and re.fullmatch(
                r"\[\s*parameters\(\s*'"
                + re.escape(expected["$parameter"])
                + r"'\s*\)\s*\]",
                actual,
                flags=re.IGNORECASE,
            )
            is not None
        )
        return matched and (
            "$https_url" not in expected
            or _matches(
                document.resolve(actual), {"$https_url": True}, document, resources
            )
        )
    if isinstance(actual, str) and actual.startswith("[") and actual.endswith("]"):
        actual = document.resolve(actual)
    if isinstance(expected, dict):
        if "$subresource" in expected:
            target = resources[expected["$subresource"]]
            value = (
                document.resource_id(target["type"], target["name"])
                + f"/{expected['collection']}/{expected['name']}".lower()
            )
            return isinstance(actual, str) and actual.lower() == value
        if "$resource" in expected:
            target = resources[expected["$resource"]]
            return isinstance(actual, str) and actual.lower() == document.resource_id(
                target["type"], target["name"]
            )
        if "$reference" in expected:
            target = resources[expected["$reference"]]
            return (
                isinstance(actual, Reference)
                and actual.resource_id
                == document.resource_id(target["type"], target["name"])
                and actual.path == expected["path"]
            )
        if "$nonempty" in expected:
            return isinstance(actual, (str, list, dict)) and bool(actual)
        if "$https_url" in expected:
            parsed = urlsplit(actual) if isinstance(actual, str) else None
            return (
                parsed is not None
                and parsed.scheme == "https"
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
            )
        if "$exact" in expected:
            return (
                isinstance(actual, list)
                and len(actual) == len(expected["$exact"])
                and _matches(actual, expected["$exact"], document, resources)
            )
        return isinstance(actual, dict) and all(
            key in actual and _matches(actual[key], value, document, resources)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        remaining = list(actual)
        for expected_item in expected:
            for index, actual_item in enumerate(remaining):
                if _matches(actual_item, expected_item, document, resources):
                    remaining.pop(index)
                    break
            else:
                return False
        return True
    return type(actual) is type(expected) and actual == expected


def evaluate_structure(
    template_path: Path, scenario_id: str, parameters: dict[str, Any] | None = None
) -> dict[str, Any]:
    contract = scenario_contract(scenario_id)
    checks: list[dict[str, Any]] = []

    def check(key: str, action: Any) -> None:
        try:
            passed = bool(action())
            checks.append({"id": key, "status": "passed" if passed else "failed"})
        except (
            ArmEvaluationError,
            ValueError,
            KeyError,
            TypeError,
            IndexError,
        ) as error:
            checks.append({"id": key, "status": "blocked", "error": str(error)})

    try:
        template = json.loads(template_path.read_text(encoding="utf-8"))
        if not isinstance(
            template, dict
        ) or "deploymentTemplate.json" not in template.get("$schema", ""):
            raise ArmEvaluationError(
                "A resource-group deployment template is required."
            )
        document = ArmDocument(template, parameters)
    except (OSError, ValueError, TypeError) as error:
        return {
            "status": "blocked",
            "checks": [],
            "error": str(error),
            "criteria_total": len(contract["resources"]) + 7,
        }
    resources = contract["resources"]
    for role, expected in resources.items():

        def resource_check(expected: dict[str, Any] = expected) -> bool:
            resource = document.find(expected["type"], expected["name"])
            wanted = {
                key: value
                for key, value in expected.items()
                if key not in ("type", "name")
            }
            return _matches(
                {key: resource.get(key) for key in wanted}, wanted, document, resources
            )

        check(f"resource:{role}", resource_check)

    def addressing() -> bool:
        networks = []
        declared_subnets = {
            (item["type"].lower(), item["name"].lower())
            for item in resources.values()
            if item["type"].lower().endswith("/subnets")
        }
        for resource in document.resources:
            if resource["type"].lower() == (NETWORK + "virtualNetworks").lower():
                properties = document.resolve(resource["properties"])
                prefixes = [
                    ipaddress.ip_network(value, strict=True)
                    for value in properties["addressSpace"]["addressPrefixes"]
                ]
                private_ranges = [
                    ipaddress.ip_network(value)
                    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
                ]
                if not prefixes or any(
                    prefix.version != 4
                    or not any(prefix.subnet_of(allowed) for allowed in private_ranges)
                    for prefix in prefixes
                ):
                    return False
                if any(
                    left.overlaps(right)
                    for index, left in enumerate(prefixes)
                    for right in prefixes[index + 1 :]
                ):
                    return False
                if any(left.overlaps(right) for left in networks for right in prefixes):
                    return False
                networks.extend(prefixes)
                subnets = [
                    item
                    for item in document.resources
                    if item["type"].lower().endswith("/subnets")
                    and item["name"].startswith(resource["name"] + "/")
                ]
                subnet_networks = []
                for subnet in subnets:
                    if (
                        subnet["type"].lower(),
                        subnet["name"].lower(),
                    ) not in declared_subnets:
                        return False
                    properties = document.resolve(subnet["properties"])
                    values = properties.get(
                        "addressPrefixes", [properties.get("addressPrefix")]
                    )
                    for value in values:
                        network = ipaddress.ip_network(value, strict=True)
                        if (
                            network.prefixlen > 29
                            or not any(network.subnet_of(parent) for parent in prefixes)
                            or any(network.overlaps(other) for other in subnet_networks)
                        ):
                            return False
                        subnet_networks.append(network)
        actual_vnets = {
            item["name"].lower()
            for item in document.resources
            if item["type"].lower() == (NETWORK + "virtualNetworks").lower()
        }
        required_vnets = {
            item["name"].lower()
            for item in resources.values()
            if item["type"].lower() == (NETWORK + "virtualNetworks").lower()
        }
        return actual_vnets == required_vnets

    check("addressing-and-completeness", addressing)
    check(
        "experiment-tags",
        lambda: all(
            isinstance(document.resolve(item.get("tags", {})).get("Experiment"), str)
            and bool(document.resolve(item["tags"])["Experiment"].strip())
            for item in document.resources
            if item["type"].lower() == (NETWORK + "virtualNetworks").lower()
        ),
    )
    check(
        "no-public-workload-nics",
        lambda: all(
            not config.get("properties", {}).get("publicIPAddress")
            or (
                scenario_id == "NET-03"
                and config.get("properties", {}).get("subnet", {}).get("id")
                == document.resource_id(
                    NETWORK + "virtualNetworks/subnets", "benchmark-vnet/web"
                )
            )
            for item in document.resources
            if item["type"].lower() == (NETWORK + "networkInterfaces").lower()
            for config in document.resolve(item.get("properties", {})).get(
                "ipConfigurations", []
            )
        ),
    )
    check(
        "standard-public-ips",
        lambda: all(
            document.resolve(item.get("sku", {})).get("name") == "Standard"
            for item in document.resources
            if item["type"].lower() == (NETWORK + "publicIPAddresses").lower()
        ),
    )
    support_types = {
        "microsoft.storage/storageaccounts",
        "microsoft.storage/storageaccounts/blobservices",
        "microsoft.storage/storageaccounts/blobservices/containers",
    }
    declared_resources = {
        (item["type"].lower(), item["name"].lower()) for item in resources.values()
    }
    check(
        "bounded-resource-types-and-scope",
        lambda: all(
            (
                item["type"].lower() in support_types
                or (item["type"].lower(), item["name"].lower()) in declared_resources
            )
            and not item.get("scope")
            for item in document.resources
        ),
    )
    check(
        "parameter-contract",
        lambda: all(
            _matches(
                template.get("parameters", {}).get(name), expected, document, resources
            )
            and not (
                expected["type"] == "secureString"
                and "defaultValue" in template["parameters"][name]
            )
            for name, expected in contract["parameters"].items()
        ),
    )

    def unique_service_names() -> bool:
        if scenario_id not in ("NET-09", "NET-10"):
            return True
        alternate_resources = {
            role: {
                **expected,
                "name": expected["name"]
                .replace("benchmark-sql-local", "benchmark-sql-cloudtest")
                .replace("benchmark-bus-local", "benchmark-bus-cloudtest"),
            }
            for role, expected in resources.items()
        }
        alternate = ArmDocument(
            template, {**(parameters or {}), "studySuffix": "cloudtest"}
        )
        for expected in alternate_resources.values():
            resource = alternate.find(expected["type"], expected["name"])
            wanted = {
                key: value
                for key, value in expected.items()
                if key not in ("type", "name")
            }
            if not _matches(
                {key: resource.get(key) for key in wanted},
                wanted,
                alternate,
                alternate_resources,
            ):
                return False
        return True

    check("unique-service-names", unique_service_names)
    return {
        "status": "passed"
        if checks and all(item["status"] == "passed" for item in checks)
        else "failed",
        "checks": checks,
        "criteria_total": len(checks),
        "criteria_passed": sum(item["status"] == "passed" for item in checks),
        "scope": "finite structural contract; deployment and runtime behavior are separate",
    }
