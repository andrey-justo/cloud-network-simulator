"""Opt-in Azure resource-group deployment and fixture-based runtime study.

Interface: AzureStudyBackend(CloudStudyConfig(...), command_runner=None).evaluate(
template_path: Path, directory: Path, scenario_id: str, runtime_checks: list[dict]).
Explicit preflight(scenario_ids: list[str]) -> list[str] returns [] on success,
otherwise sanitized blocking reasons. It checks configuration, parameter and
scenario bindings, login/subscription/capabilities and existing source VM/NIC
identities using read-only CLI calls. It creates no files/resources, generates
no keys and installs no listeners. Construction does not call preflight; planning
must not call it. Binding completeness means nonempty declared sources and
destinations and valid cross-references/expectations, not completeness against
an unavailable scenario check specification. Service-only scenarios may omit
sources/destinations when nonempty service_resources are declared. Template/network existence,
fixture readiness and actual probe outcomes remain evaluate-time checks.
The injectable runner follows subprocess.run's signature and returns a
CompletedProcess with JSON stdout. No shell is used; each CLI call has a timeout.
Only resource-group ARM JSON templates are accepted (compile Bicep beforehand).
The caller must supply an already locally validated template; Azure validation
is repeated here. Nested/linked deployments are deliberately unsupported.

Runtime bindings are operator-authored JSON, keyed by exact scenario ID::

    {"NET-01": {
      "sources": {
        "web": {"vnet": "benchmark-vnet", "subnet": "web",
                "vm_size": "Standard_B1s", "private_ip_address": "10.1.1.4"},
        "app": {"vnet": "benchmark-vnet", "subnet": "app",
                "vm_size": "Standard_B1s", "location": "eastus"},
        "external": "/subscriptions/SUB/resourceGroups/fixtures/providers/Microsoft.Compute/virtualMachines/probe"},
      "source_ips": {"web": "10.1.1.4"},
      "destinations": {"app": {"source": "app", "listener_ports": [443]},
                       "web": {"source": "web", "listener_ports": [80],
                               "expected_body": "study-{study_suffix}"},
                       "gateway": {"address": "gateway.example.org",
                                   "expected_body": "study-{study_suffix}"},
                       "internet": "api.ipify.org",
                       "database": "db.internal"},
      "expected_egress_ip": {"resource_type": "nat_gateway", "name": "benchmark-nat"},
      "dns_private_addresses": {
        "database": {"private_endpoint": "benchmark-sql-pe"}},
      "service_resources": {
        "sql": {"resource_type": "Microsoft.Sql/servers",
                "name": "benchmark-sql-{study_suffix}"},
        "bus": {"resource_type": "Microsoft.ServiceBus/namespaces",
                "name": "benchmark-bus-{study_suffix}"}},
      "route_destinations": {"app": {
        "next_hop_type": "VirtualAppliance", "next_hop_ip": "10.1.0.4"}}
    }}

SUB must equal config.subscription_id. String sources are explicit existing
operator-provisioned Linux VMs (external vantage points must use this form).
Object sources opt into Ubuntu2204 fixture provisioning in the newly deployed
candidate group's named VNet/subnet, never an external network. Objects require
vnet, subnet, vm_size and optionally location (must match VNet location) and
private_ip_address (static IPv4, checked against the actual candidate subnet).
The first four subnet addresses and final address are rejected as Azure-reserved.
The address is passed to NIC creation via --private-ip-address and verified on
the resulting NIC before VM creation. VM creation then attaches that exact NIC;
Azure CLI forbids combining VM --nics with VM --private-ip-address.
This supports fixed gateway backends without assuming dynamic allocation order.
Names
are literal Azure names, e.g. benchmark-* / web, app, data, hub, workload, spoke1,
spoke2. A dedicated NIC has no public IP or NIC NSG and inherits subnet NSG, except the
explicit NET-03-only public web fixture described below. String source VMs'
NIC/subnet IDs are inspected to require same-subscription networks outside the
candidate RG; an operator must choose a real external vantage point (this does
not prove absence of private peering or a particular egress path).
Only scenario NET-03 / role web / subnet web may declare public_ip:true.
That opt-in creates a Standard static IPv4 address in the owned RG and attaches
it without a NIC NSG override. All other fixture NICs remain private.
{"source": "web", "address_kind": "public"} resolves that public endpoint;
omitting address_kind (or using "private") resolves the fixture private IP.
Declare separate destination roles for public/internal observations if needed.
SSH keys are generated locally under directory/study-cloud-<uuid>/; private keys
are never read or logged and are removed in key-generation finally, including
failed/partial generation. Only public keys are retained for VM provisioning;
Run Command needs no SSH private key. Existing operator-owned files are never
overwritten or removed. Removal failures are recorded as blocked cleanup
operations and block the affected fixture without hiding earlier errors.
CLI provisioning/agent/egress failures block the relevant checks.
Destination strings are explicit addresses; {"address": "..."} is equivalent.
{"public_ip": "benchmark-gateway-pip", "expected_body": "study-{study_suffix}"}
resolves an exact named public IP from the candidate RG for a gateway target.
Address strings and expected_body markers support literal {study_suffix} and
{resource_group} substitutions. If the ARM template declares studySuffix:string,
both validate/create receive the same unique run ID override after the operator
parameters file. It is never necessary to write merged secret parameters.
{"source": "role"} resolves a created fixture's exact private IP (or an existing
VM's explicit source_ips entry). Only fixture-reference destinations may declare
listener_ports (unique ports 1..65535): a fixed Python TCP echo service is started
using run-command. No listeners are installed by default. Services are study
fixtures, not production servers; no package installation is attempted. Inbound
and internet tests require an explicitly configured external vantage point when
the scenario demands one: this backend does not manufacture internet reachability.
With expected_body, listeners instead serve an exact fixed HTTP response marker.
Markers must be 8..256 ASCII letters/digits/dot/underscore/hyphen and include
{study_suffix} (expanded run ID), preventing unrelated HTTP servers from passing.
HTTP checks require an explicit existing external VM source, port, and destination
expected_body. They GET / without redirects or environment proxies and compare
the entire successful response body, not a TCP handshake. Use external->gateway
with the same marker on the candidate web listener for App Gateway studies.
Fixtures are never created in gateway, ApplicationGatewaySubnet, or
AzureFirewallSubnet subnets; operator-declared dedicated gateway subnets must
also not be used as source fixtures.
Each check has a unique nonempty id, kind (tcp, http, egress_ip,
dns_private, route, public_access_disabled), source/destination role, optional boolean expected (default
True), and, for tcp/http, required integer port (1..65535). TCP uses Network Watcher.
Egress uses a fixed HTTPS api.ipify.org request from the fixture; the destination
must bind to that exact hostname. DNS requires successful resolution and an
exact match with the configured non-public address set. dns_private_addresses values may
be explicit IP lists or {"private_endpoint": "benchmark-sql-pe"}: after deployment
the latter resolves IPs from that exact candidate-RG endpoint's NICs. Connections
must be Approved; endpoint, NIC and subnet IDs must belong to the candidate RG
and configured subscription. Missing/unapproved/malformed endpoints block DNS
checks, never substitute successful DNS resolution for endpoint-IP evidence.
Endpoint names support {study_suffix}/{resource_group} substitutions.
Preflight checks only these declarations/capabilities, not not-yet-created PEs.
public_access_disabled is a post-deployment control-plane observation, NOT an
end-to-end protocol test: source must be the literal "control-plane", destination
must be sql or bus, with a matching service_resources entry of the exact type
Microsoft.Sql/servers or Microsoft.ServiceBus/namespaces respectively. No VM
source is required. Resource names safely expand {study_suffix}/{resource_group}.
Read-only resource show must return that exact candidate-RG/subscription resource
ID and publicNetworkAccess exactly Disabled to meet expected=True. Enabled is a
valid failing observation; absent/unknown properties and tool errors block.
Shared SQL/Service Bus public frontends may still accept TCP handshakes despite
disabled public access; this property observation deliberately makes no claim
about those handshakes or authenticated protocol behavior.
Route checks require
source_ips, an IP destination, and both expected next-hop fields. A check's
expected_next_hop_type can supply the type instead of the binding (conflicts
block); next_hop_ip remains required except for type None (discard). Discard
routes accept omitted/null/empty/"0.0.0.0" IPs as the same no-IP sentinel.
next_hop_ip may alternatively be {"firewall": "benchmark-firewall"}; this resolves
the exact trial-RG firewall's sole data-plane private IP after deployment.
Only VirtualAppliance expectations may use this firewall form. Egress expectations may be an explicit
operator IP string, or preferably {"resource_type": "nat_gateway"|"firewall",
"name": "..."} resolved through the candidate RG's exact resource and public
IP IDs. This latter form requires exactly one public egress IP; multiple-IP,
prefix and computed egress paths are blocked, not guessed. expected=False
inverts only a valid observation, NEVER a timeout, tool error or malformed data.
Run-command uses fixed Python 3 scripts; fixtures need Python 3, the VM agent,
and the relevant networking/Network Watcher prerequisites already provisioned.

Preflight checks login, subscription state, provider registration and effective
subscription-level permissions. Scoped-only permissions are conservatively
rejected. No login, provider registration, fixture creation or paid API call
occurs unless explicitly enabled. All Azure CLI calls specify the subscription.
Deployments may incur Azure costs. Templates/parameters/bindings must be trusted:
this is a study guard, not a sandbox for arbitrary ARM expressions or resources.
Literal cross-subscription IDs and explicit foreign subscriptionId fields are
rejected, but arbitrary computed ARM expressions cannot be statically proven.

Each run writes study-cloud-<uuid>.json under directory, containing only
allowlisted operation names/statuses, result codes and resource-group identity.
CLI output/errors, commands, template/parameter contents and probe output are
never included in evidence. parameters_file accepts either an ARM parameter
document (parameters plus optional $schema/contentVersion) or exactly::

    {"scenarios": {"NET-10": {"parameters": {
        "sqlAdministratorPassword": {"value": "operator-supplied-secret"}}}}}

Scenario entries must contain only an object parameters; each parameter must
contain exactly value or an object reference. Flat/scenario schemas cannot be
mixed. All entries are validated, including unselected scenarios, and unknown
parameter names are never filtered. An unspecified scenario selects an empty
parameter map. Both validate/create use the same selected parameters followed
by the studySuffix override, only if the template declares studySuffix.
For scenario files the selected ARM document is written with exclusive creation
and mode 0600 beneath this run's directory, passed by @file (never secret argv),
and removed in finally regardless of deployment/cleanup outcome. Flat files are
passed unchanged and never removed. No merged secrets are written to evidence;
parameters_cleanup_error explicitly reports failure to remove a selected file.
OS/directory ACLs must also protect the run directory, particularly on Windows.
Cleanup deletes only the unique, newly-created group after re-reading its
per-run ownership tag. Cleanup failure is reported separately and never hides
an earlier failure; cleanup=False reports retained_resource_group explicitly.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import fnmatch
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Callable
import uuid


@dataclass
class CloudStudyConfig:
    enabled: bool = False
    subscription_id: str = ""
    location: str = ""
    resource_group_prefix: str = "iac-study"
    parameters_file: str | None = None
    runtime_bindings_file: str | None = None
    cleanup: bool = True


class _Blocked(Exception):
    pass


def _json_loads(text):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate_json_key")
            value[key] = item
        return value

    def constant(_):
        raise ValueError("nonfinite_json_number")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


_OWNER_TAG = "iac-study-run"
_TIMEOUT = 180
_DEPLOY_TIMEOUT = 900
_VM_ID = re.compile(
    r"/subscriptions/([^/]+)/resourceGroups/([^/]+)/providers/"
    r"Microsoft\.Compute/virtualMachines/([^/]+)", re.IGNORECASE
)
_NEXT_HOPS = {
    "Internet", "VirtualAppliance", "VirtualNetworkGateway", "VnetLocal",
    "HyperNetGateway", "None",
}
_SERVICE_TYPES = {
    "sql": "Microsoft.Sql/servers",
    "bus": "Microsoft.ServiceBus/namespaces",
}
_EGRESS_SCRIPT = (
    "python3 - <<'PY'\n"
    "import json, urllib.request\n"
    "with urllib.request.urlopen('https://api.ipify.org?format=json', timeout=20) as r:\n"
    "    data = json.load(r)\n"
    "print(json.dumps({'egress_ip': data['ip']}))\n"
    "PY"
)
_DNS_SCRIPT = (
    "python3 - <<'PY'\n"
    "import json, socket\n"
    "socket.setdefaulttimeout(20)\n"
    "print(json.dumps({'addresses': sorted({r[4][0] for r in "
    "socket.getaddrinfo(HOST, None)})}))\n"
    "PY"
)
_LISTENER_SCRIPT = (
    "python3 - <<'PY'\n"
    "import json, subprocess, sys\n"
    "code = \"import socket,threading,time\\n"
    "def serve(port):\\n"
    " s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); "
    "s.bind(('0.0.0.0',port)); s.listen(16)\\n"
    " while True:\\n"
    "  c,_=s.accept(); c.settimeout(2)\\n"
    "  try: c.sendall(c.recv(1024))\\n"
    "  except OSError: pass\\n"
    "  finally: c.close()\\n"
    "for p in PORTS: threading.Thread(target=serve,args=(p,),daemon=True).start()\\n"
    "while True: time.sleep(60)\\n\"\n"
    "subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.DEVNULL,\n"
    " stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)\n"
    "import socket, time\n"
    "time.sleep(2)\n"
    "for port in PORTS:\n"
    " with socket.create_connection(('127.0.0.1', port), timeout=3) as c:\n"
    "  c.sendall(b'study-probe'); assert c.recv(1024) == b'study-probe'\n"
    "print(json.dumps({'listener_ports': PORTS}))\n"
    "PY"
)
_HTTP_LISTENER_SCRIPT = _LISTENER_SCRIPT.replace(
    "c.sendall(c.recv(1024))",
    "c.recv(4096); c.sendall(b'HTTP/1.0 200 OK\\\\r\\\\n"
    "Content-Type: text/plain\\\\r\\\\nConnection: close\\\\r\\\\n"
    "Content-Length: BODY_LENGTH\\\\r\\\\n\\\\r\\\\nBODY_MARKER')",
).replace(
    "c.sendall(b'study-probe'); assert c.recv(1024) == b'study-probe'",
    "c.sendall(b'GET / HTTP/1.0\\r\\n\\r\\n'); "
    "assert b'BODY_MARKER' in c.recv(4096)",
)
_HTTP_SCRIPT = (
    "python3 - <<'PY'\n"
    "import json, urllib.request\n"
    "class NoRedirect(urllib.request.HTTPRedirectHandler):\n"
    " def redirect_request(self, req, fp, code, msg, headers, newurl): return None\n"
    "opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())\n"
    "with opener.open(URL, timeout=20) as r:\n"
    " print(json.dumps({'status': r.status, 'body': r.read(4097).decode('utf-8')}))\n"
    "PY"
)


class AzureStudyBackend:
    def __init__(
        self, config: CloudStudyConfig, command_runner: Callable | None = None
    ):
        self.config = config
        self.command_runner = command_runner or subprocess.run

    def preflight(self, scenario_ids: list[str]) -> list[str]:
        """Return blocking reasons; explicitly opt into read-only Azure checks."""
        if self.config.enabled is not True:
            return ["cloud_disabled"]
        try:
            self._validate_config()
            if (not isinstance(scenario_ids, list) or not scenario_ids
                    or any(not isinstance(s, str) or not s.strip() for s in scenario_ids)
                    or len(set(scenario_ids)) != len(scenario_ids)):
                raise _Blocked("invalid_scenario_ids")
            self._parameter_file()
            if not self.config.runtime_bindings_file:
                raise _Blocked("runtime_bindings_file_required")
            document = _json_loads(
                Path(self.config.runtime_bindings_file).read_text(encoding="utf-8-sig")
            )
            if not isinstance(document, dict):
                raise _Blocked("invalid_bindings")
            self._guard_ids(document)
            issues = []
            scenarios = {}
            for scenario in scenario_ids:
                try:
                    bindings = document.get(scenario)
                    self._binding_preflight(bindings, scenario)
                    scenarios[scenario] = bindings
                except _Blocked as exc:
                    issues.append(f"{scenario}:{exc}")
                except (ValueError, TypeError, KeyError, AttributeError):
                    issues.append(f"{scenario}:invalid_runtime_bindings")
            if issues:
                return issues
            # Check the union once; never create a candidate group in preflight.
            combined = {"sources": {}, "destinations": {}, "service_resources": {}}
            kinds = set()
            for scenario, bindings in scenarios.items():
                for section in ("sources", "destinations"):
                    combined[section].update({
                        f"{scenario}:{role}": spec for role, spec in bindings.get(section, {}).items()
                    })
                if bindings.get("destinations"):
                    kinds.add("tcp")
                if bindings.get("service_resources"):
                    kinds.add("public_access_disabled")
                    combined["service_resources"].update({
                        f"{scenario}:{role}": spec for role, spec in bindings["service_resources"].items()
                    })
                if bindings.get("route_destinations"):
                    kinds.add("route")
                    combined.setdefault("route_destinations", {}).update({
                        f"{scenario}:{role}": spec
                        for role, spec in bindings["route_destinations"].items()
                    })
                if bindings.get("dns_private_addresses"):
                    kinds.add("dns_private")
                    combined.setdefault("dns_private_addresses", {}).update({
                        f"{scenario}:{role}": spec
                        for role, spec in bindings["dns_private_addresses"].items()
                    })
                if "expected_egress_ip" in bindings:
                    kinds.add("egress_ip")
                    if isinstance(bindings["expected_egress_ip"], dict):
                        combined["expected_egress_ip"] = bindings["expected_egress_ip"]
                if any(isinstance(d, dict) and "expected_body" in d
                       for d in bindings.get("destinations", {}).values()):
                    kinds.add("http")
            trace = {"operations": []}
            self._preflight(trace, combined, [{"kind": k} for k in sorted(kinds)])
            inspected = set()
            for bindings in scenarios.values():
                for source in bindings.get("sources", {}).values():
                    if not isinstance(source, str) or source.lower() in inspected:
                        continue
                    vm = self._az(trace, "preflight_external_source", [
                        "vm", "show", "--ids", source,
                        "--query", "{id:id,networkProfile:networkProfile}",
                    ])
                    if not isinstance(vm, dict) or str(vm.get("id", "")).lower() != source.lower():
                        raise _Blocked("source_vm_identity_mismatch")
                    self._external_source_network(trace, vm, "")
                    inspected.add(source.lower())
            return []
        except _Blocked as exc:
            return [str(exc)]
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return ["invalid_configuration_or_input"]

    def _binding_preflight(self, bindings, scenario):
        if not isinstance(bindings, dict):
            raise _Blocked("runtime_bindings_missing")
        services = bindings.get("service_resources", {})
        if not isinstance(services, dict):
            raise _Blocked("invalid_service_resources")
        for role, spec in services.items():
            self._service_name(role, spec, "0" * 32, "preflight-group")
        if services:
            bindings = dict(bindings)
            bindings.setdefault("sources", {})
            bindings.setdefault("destinations", {})
        for section in ("sources", "destinations"):
            if not isinstance(bindings.get(section), dict) or (
                not bindings[section] and not services
            ):
                raise _Blocked(f"nonempty_{section}_required")
            if any(not role.strip() for role in bindings[section]):
                raise _Blocked("invalid_binding_role")
        if bindings["destinations"] and not bindings["sources"]:
            raise _Blocked("nonempty_sources_required")
        source_ips = bindings.get("source_ips", {})
        if not isinstance(source_ips, dict):
            raise _Blocked("invalid_source_ips")
        for role, ip in source_ips.items():
            if role not in bindings["sources"]:
                raise _Blocked("unknown_source_ip_role")
            self._ip(ip)
        for role, source in bindings["sources"].items():
            if isinstance(source, str):
                match = _VM_ID.fullmatch(source)
                if not match or match[1].lower() != self.config.subscription_id.lower():
                    raise _Blocked("explicit_source_vm_required")
            else:
                self._validate_fixture_spec(source, role, scenario)
                if "location" in source and not re.fullmatch(
                    r"[A-Za-z][A-Za-z0-9-]{1,63}", source["location"]
                ):
                    raise _Blocked("invalid_fixture_location")
        suffix = "0" * 32
        for role, destination in bindings["destinations"].items():
            if isinstance(destination, str):
                self._destination(self._expand(destination, suffix, "preflight-group"))
                continue
            if not isinstance(destination, dict):
                raise _Blocked("invalid_destination_binding")
            marker = destination.get("expected_body")
            if marker is not None and (
                not isinstance(marker, str) or "{study_suffix}" not in marker
                or not re.fullmatch(r"[A-Za-z0-9_.-]{8,256}",
                                    self._expand(marker, suffix, "preflight-group"))
            ):
                raise _Blocked("unique_http_marker_required")
            if "address" in destination and not set(destination) - {"address", "expected_body"}:
                self._destination(self._expand(destination["address"], suffix, "preflight-group"))
            elif "public_ip" in destination and not set(destination) - {"public_ip", "expected_body"}:
                name = self._expand(destination["public_ip"], suffix, "preflight-group")
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", name):
                    raise _Blocked("invalid_public_ip_name")
            elif "source" in destination and not set(destination) - {
                "source", "address_kind", "listener_ports", "expected_body",
            }:
                source_role = destination["source"]
                if not isinstance(source_role, str) or source_role not in bindings["sources"]:
                    raise _Blocked("unknown_destination_source")
                source = bindings["sources"][source_role]
                kind = destination.get("address_kind", "private")
                if kind not in {"private", "public"}:
                    raise _Blocked("invalid_destination_address_kind")
                if kind == "public" and (
                    not isinstance(source, dict) or source.get("public_ip") is not True
                ):
                    raise _Blocked("public_destination_requires_public_fixture")
                if kind == "private" and isinstance(source, str) and source_role not in source_ips:
                    raise _Blocked("destination_source_ip_required")
                ports = destination.get("listener_ports", [])
                if not isinstance(ports, list) or any(
                    type(port) is not int or not 1 <= port <= 65535 for port in ports
                ) or len(set(ports)) != len(ports):
                    raise _Blocked("invalid_listener_ports")
                if ports and not isinstance(source, dict):
                    raise _Blocked("listeners_require_owned_fixture")
            else:
                raise _Blocked("invalid_destination_binding")
        for section in ("dns_private_addresses", "route_destinations"):
            values = bindings.get(section, {})
            if not isinstance(values, dict) or any(
                role not in bindings["destinations"] for role in values
            ):
                raise _Blocked("unknown_or_invalid_expectation_role")
        for addresses in bindings.get("dns_private_addresses", {}).values():
            if isinstance(addresses, dict):
                self._private_endpoint_name(addresses, suffix, "preflight-group")
                continue
            if not isinstance(addresses, list) or not addresses:
                raise _Blocked("explicit_private_addresses_required")
            for address in addresses:
                ip = self._ip(address)
                if not ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
                    raise _Blocked("invalid_private_addresses")
        for route in bindings.get("route_destinations", {}).values():
            if not isinstance(route, dict) or (
                "next_hop_type" in route and route["next_hop_type"] not in _NEXT_HOPS
            ):
                raise _Blocked("explicit_route_expectation_required")
            ip = route.get("next_hop_ip")
            if isinstance(ip, dict):
                self._firewall_route_name(ip, suffix, "preflight-group")
                if route.get("next_hop_type", "VirtualAppliance") != "VirtualAppliance":
                    raise _Blocked("firewall_route_requires_virtual_appliance")
            elif route.get("next_hop_type") == "None" and ip in (None, "", "0.0.0.0"):
                continue
            elif not isinstance(ip, str):
                raise _Blocked("explicit_route_expectation_required")
            elif ip:
                self._ip(ip)
            elif route.get("next_hop_type") == "VirtualAppliance":
                raise _Blocked("explicit_route_expectation_required")
        if "expected_egress_ip" in bindings:
            expectation = bindings["expected_egress_ip"]
            if isinstance(expectation, dict):
                if set(expectation) != {"resource_type", "name"} or (
                    expectation["resource_type"] not in {"nat_gateway", "firewall"}
                    or not isinstance(expectation["name"], str)
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", expectation["name"])
                ):
                    raise _Blocked("invalid_egress_resource")
            else:
                self._ip(expectation)

    @staticmethod
    def _validate_fixture_spec(spec, role, scenario_id):
        if not isinstance(spec, dict) or (
            set(spec) - {
                "vnet", "subnet", "vm_size", "location", "public_ip", "private_ip_address",
            }
            or any(not isinstance(spec.get(k), str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", spec[k]
            ) for k in ("vnet", "subnet", "vm_size"))
            or type(spec.get("public_ip", False)) is not bool
        ):
            raise _Blocked("invalid_fixture_specification")
        if spec.get("public_ip", False) and (
            scenario_id != "NET-03" or role != "web" or spec["subnet"].lower() != "web"
        ):
            raise _Blocked("public_fixture_only_net03_web")
        if spec["subnet"].lower() in {
            "gateway", "applicationgatewaysubnet", "azurefirewallsubnet",
        }:
            raise _Blocked("dedicated_gateway_subnet_not_a_fixture")
        if "private_ip_address" in spec:
            if not isinstance(spec["private_ip_address"], str):
                raise _Blocked("invalid_fixture_static_ip")
            try:
                ip = ipaddress.IPv4Address(spec["private_ip_address"])
            except ValueError:
                raise _Blocked("invalid_fixture_static_ip") from None
            if not ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
                raise _Blocked("invalid_fixture_static_ip")

    def evaluate(
        self, template_path: Path, directory: Path, scenario_id: str,
        runtime_checks: list[dict],
    ) -> dict:
        run_id = uuid.uuid4().hex
        evidence = Path(directory) / f"study-cloud-{run_id}.json"
        checks = [
            {"id": check.get("id") if isinstance(check, dict)
             and isinstance(check.get("id"), str) else None,
             "status": "blocked", "reason": "deployment_not_available"}
            for check in runtime_checks
        ]
        result = {
            "deployment_status": "disabled" if self.config.enabled is not True else "blocked",
            "runtime_status": "blocked" if checks else "not_requested",
            "runtime_checks": checks,
            "cleanup_status": "not_required",
            "operations": [],
            "evidence_file": str(evidence),
        }
        group = None
        creation_attempted = False
        selected_parameters_path = None
        try:
            if self.config.enabled is not True:
                result["reason"] = "cloud_disabled"
            else:
                self._validate_config()
                template = _json_loads(Path(template_path).read_text(encoding="utf-8-sig"))
                self._validate_template(template)
                parameters, scenarios = self._parameter_file()
                bindings = {}
                if self.config.runtime_bindings_file:
                    document = _json_loads(
                        Path(self.config.runtime_bindings_file).read_text(encoding="utf-8-sig")
                    )
                    self._guard_ids(document)
                    if not isinstance(document, dict):
                        raise _Blocked("invalid_bindings")
                    bindings = document.get(scenario_id, {})
                    if not isinstance(bindings, dict):
                        raise _Blocked("invalid_bindings")
                self._preflight(result, bindings, runtime_checks)
                group = f"{self.config.resource_group_prefix}-{run_id}"
                result["resource_group"] = group
                exists = self._az(result, "group_exists", ["group", "exists", "--name", group])
                if exists is not False:
                    raise _Blocked("resource_group_not_absent")
                # Even a timed-out create may have created the tagged group.
                creation_attempted = True
                created = self._az(result, "group_create", [
                    "group", "create", "--name", group, "--location", self.config.location,
                    "--tags", f"{_OWNER_TAG}={run_id}",
                    "--query", "{id:id,name:name,tags:tags}",
                ])
                self._owned_group(created, group, run_id)
                if scenarios is not None:
                    selected = scenarios.get(scenario_id, {"parameters": {}})
                    selected_path = (
                        Path(directory).resolve() / f"study-cloud-{run_id}" / "parameters.json"
                    )
                    selected_path.parent.mkdir(parents=True, exist_ok=True)
                    descriptor = os.open(
                        selected_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                    )
                    selected_parameters_path = selected_path
                    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                        json.dump(selected, stream)
                    parameters = selected_path
                deployment = [
                    "--resource-group", group, "--name", f"study-{run_id}",
                    "--template-file", str(Path(template_path).resolve()),
                ]
                if parameters:
                    deployment += ["--parameters", f"@{parameters}"]
                declared = template.get("parameters", {}).get("studySuffix")
                if declared is not None:
                    if not isinstance(declared, dict) or declared.get("type") != "string":
                        raise _Blocked("invalid_study_suffix_parameter")
                    if not parameters:
                        deployment += ["--parameters"]
                    deployment += [f"studySuffix={run_id}"]
                result["study_suffix"] = run_id
                validated = self._az(
                    result, "deployment_validate",
                    ["deployment", "group", "validate", *deployment],
                    timeout=_DEPLOY_TIMEOUT,
                )
                if (not isinstance(validated, dict) or validated.get("error")
                        or not isinstance(validated.get("properties"), dict)
                        or validated["properties"].get("provisioningState") != "Succeeded"):
                    raise _Blocked("invalid_validation_response")
                result["deployment_status"] = "failed"
                state = self._az(
                    result, "deployment_create",
                    ["deployment", "group", "create", *deployment,
                     "--query", "properties.provisioningState"],
                    timeout=_DEPLOY_TIMEOUT,
                )
                if state != "Succeeded":
                    raise _Blocked("deployment_not_succeeded")
                result["deployment_status"] = "passed"
                bindings = self._fixtures(
                    result, bindings, group, run_id, Path(directory), scenario_id
                )
                seen = set()
                duplicate_ids = {
                    c.get("id") for c in runtime_checks if isinstance(c, dict)
                    and isinstance(c.get("id"), str)
                    and sum(isinstance(x, dict) and x.get("id") == c["id"]
                            for x in runtime_checks) > 1
                }
                for check, outcome in zip(runtime_checks, checks):
                    try:
                        self._validate_check(check, seen, duplicate_ids)
                        observed = self._probe(result, check, bindings)
                        outcome.update(
                            status="passed" if observed == check.get("expected", True) else "failed",
                            reason="expectation_met" if observed == check.get("expected", True)
                            else "expectation_not_met",
                        )
                    except _Blocked as exc:
                        outcome["reason"] = str(exc)
                    except (ValueError, TypeError, KeyError, AttributeError):
                        outcome["reason"] = "invalid_probe_data"
                result["runtime_status"] = (
                    "failed" if any(c["status"] == "failed" for c in checks) else
                    "blocked" if any(c["status"] == "blocked" for c in checks) else
                    "passed" if checks else "not_requested"
                )
        except _Blocked as exc:
            result["reason"] = str(exc)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            result["reason"] = "invalid_configuration_or_input"
        finally:
            if selected_parameters_path is not None:
                try:
                    selected_parameters_path.unlink()
                except OSError:
                    result["parameters_cleanup_error"] = "parameter_file_removal_failed"
            if creation_attempted:
                if self.config.cleanup:
                    try:
                        current = self._az(result, "cleanup_inspect", [
                            "group", "show", "--name", group,
                            "--query", "{id:id,name:name,tags:tags}",
                        ])
                        self._owned_group(current, group, run_id)
                        self._az(result, "cleanup_delete", [
                            "group", "delete", "--name", group, "--yes",
                        ], allow_empty=True, timeout=_DEPLOY_TIMEOUT)
                        absent = self._az(result, "cleanup_verify", [
                            "group", "exists", "--name", group,
                        ])
                        if absent is not False:
                            raise _Blocked("cleanup_not_confirmed")
                        result["cleanup_status"] = "passed"
                    except _Blocked as exc:
                        result["cleanup_status"] = "failed"
                        result["cleanup_reason"] = str(exc)
                        result["retained_resource_group"] = group
                else:
                    result["cleanup_status"] = "retained"
                    result["retained_resource_group"] = group
            # Evidence is deliberately an allowlist: never include CLI diagnostics.
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    def _parameter_file(self):
        if not self.config.parameters_file:
            return None, None
        path = Path(self.config.parameters_file).resolve(strict=True)
        document = _json_loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(document, dict):
            raise _Blocked("invalid_parameters_file")
        self._guard_ids(document)

        def validate_parameters(parameters):
            if not isinstance(parameters, dict):
                raise _Blocked("invalid_parameter_entries")
            for name, value in parameters.items():
                if not name.strip() or not isinstance(value, dict) or (
                    set(value) != {"value"} and (
                        set(value) != {"reference"} or not isinstance(value["reference"], dict)
                    )
                ):
                    raise _Blocked("invalid_parameter_entries")

        if "scenarios" in document:
            if set(document) != {"scenarios"}:
                raise _Blocked("mixed_parameter_schemas")
            scenarios = document["scenarios"]
            if not isinstance(scenarios, dict):
                raise _Blocked("invalid_parameter_scenarios")
            for scenario, entry in scenarios.items():
                if not scenario.strip() or not isinstance(entry, dict) or set(entry) != {"parameters"}:
                    raise _Blocked("invalid_parameter_scenario_entry")
                validate_parameters(entry["parameters"])
            return path, scenarios
        if set(document) - {"$schema", "contentVersion", "parameters"} or "parameters" not in document:
            raise _Blocked("invalid_flat_parameter_schema")
        if any(key in document and not isinstance(document[key], str)
               for key in ("$schema", "contentVersion")):
            raise _Blocked("invalid_flat_parameter_schema")
        validate_parameters(document["parameters"])
        return path, None

    def _validate_config(self):
        c = self.config
        if type(c.cleanup) is not bool:
            raise _Blocked("explicit_cleanup_boolean_required")
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", c.subscription_id):
            raise _Blocked("explicit_subscription_required")
        try:
            uuid.UUID(c.subscription_id)
        except ValueError:
            raise _Blocked("explicit_subscription_required") from None
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9-]{1,63}", c.location):
            raise _Blocked("explicit_location_required")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,40}", c.resource_group_prefix):
            raise _Blocked("invalid_resource_group_prefix")

    def _guard_ids(self, value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() == "subscriptionid" and (
                    not isinstance(item, str)
                    or item.lower() != self.config.subscription_id.lower()
                ):
                    raise _Blocked("foreign_or_computed_subscription")
                self._guard_ids(item)
        elif isinstance(value, list):
            for item in value:
                self._guard_ids(item)
        elif isinstance(value, str):
            for subscription in re.findall(r"/subscriptions/([^/\s'\"\\]+)", value, re.I):
                if subscription.lower() != self.config.subscription_id.lower():
                    raise _Blocked("foreign_resource_id")

    def _validate_template(self, template):
        if not isinstance(template, dict):
            raise _Blocked("unsupported_template")
        schema = template.get("$schema", "")
        if not isinstance(schema, str) or not re.fullmatch(
            r"https?://schema\.management\.azure\.com/schemas/"
            r"(2019-04-01|2015-01-01)/deploymentTemplate\.json#?", schema, re.I
        ):
            raise _Blocked("unsupported_template_scope")
        resources = template.get("resources")
        if not isinstance(resources, list):
            raise _Blocked("unsupported_template_resources")
        self._guard_ids(template)

        def inspect(resources):
            for resource in resources:
                if not isinstance(resource, dict):
                    raise _Blocked("unsupported_template_resources")
                kind = resource.get("type", "")
                if not isinstance(kind, str) or "[" in kind or kind.lower() == "microsoft.resources/deployments":
                    raise _Blocked("nested_or_computed_deployment_unsupported")
                if "scope" in resource:
                    raise _Blocked("explicit_resource_scope_unsupported")
                children = resource.get("resources", [])
                if not isinstance(children, list):
                    raise _Blocked("unsupported_template_resources")
                inspect(children)
        inspect(resources)

    def _az(self, result, operation, args, *, timeout=_TIMEOUT, allow_empty=False):
        entry = {"operation": operation, "status": "blocked"}
        result["operations"].append(entry)
        try:
            completed = self.command_runner(
                ["az", *args, "--subscription", self.config.subscription_id,
                 "--only-show-errors", "--output", "json"],
                capture_output=True, text=True, shell=False, timeout=timeout,
            )
            if completed.returncode != 0:
                raise _Blocked("azure_command_failed")
            output = completed.stdout.strip()
            parsed = None if not output and allow_empty else _json_loads(output)
            entry["status"] = "passed"
            return parsed
        except _Blocked:
            entry["reason"] = "azure_command_failed"
            raise
        except subprocess.TimeoutExpired:
            entry["reason"] = "azure_command_timeout"
            raise _Blocked("azure_command_timeout") from None
        except (OSError, ValueError, TypeError, AttributeError):
            entry["reason"] = "azure_command_invalid_or_unavailable"
            raise _Blocked("azure_command_invalid_or_unavailable") from None

    def _preflight(self, result, bindings, checks):
        account = self._az(result, "preflight_account", ["account", "show"])
        if not isinstance(account, dict) or (
            str(account.get("id", "")).lower() != self.config.subscription_id.lower()
            or account.get("state") != "Enabled"
        ):
            raise _Blocked("subscription_not_enabled")
        sources = bindings.get("sources", {})
        if not isinstance(sources, dict):
            raise _Blocked("invalid_sources")
        fixtures = any(isinstance(source, dict) for source in sources.values())
        kinds = {c.get("kind") for c in checks if isinstance(c, dict)
                 and isinstance(c.get("kind"), str)}
        network_checks = bool(kinds & {"tcp", "http", "dns_private", "egress_ip", "route"})
        providers = ["Microsoft.Resources"]
        if network_checks or fixtures or sources:
            providers += ["Microsoft.Compute", "Microsoft.Network"]
        services = bindings.get("service_resources", {})
        if not isinstance(services, dict):
            raise _Blocked("invalid_service_resources")
        for spec in services.values():
            if not isinstance(spec, dict) or spec.get("resource_type") not in _SERVICE_TYPES.values():
                raise _Blocked("invalid_service_resource_type")
            namespace = spec["resource_type"].split("/", 1)[0]
            if namespace not in providers:
                providers.append(namespace)
        for namespace in providers:
            provider = self._az(result, "preflight_provider", [
                "provider", "show", "--namespace", namespace,
                "--query", "registrationState",
            ])
            if provider != "Registered":
                raise _Blocked("resource_provider_not_registered")
        permissions = self._az(result, "preflight_permissions", [
            "rest", "--method", "get", "--url",
            f"https://management.azure.com/subscriptions/{self.config.subscription_id}"
            "/providers/Microsoft.Authorization/permissions?api-version=2022-04-01",
        ])
        if not isinstance(permissions, dict) or not isinstance(permissions.get("value"), list):
            raise _Blocked("invalid_permissions_response")
        required = (
            "Microsoft.Resources/subscriptions/resourceGroups/read",
            "Microsoft.Resources/subscriptions/resourceGroups/write",
            "Microsoft.Resources/deployments/read",
            "Microsoft.Resources/deployments/write",
            "Microsoft.Resources/deployments/validate/action",
        )
        if self.config.cleanup:
            required += ("Microsoft.Resources/subscriptions/resourceGroups/delete",)
        if network_checks or fixtures or sources:
            required += ("Microsoft.Compute/virtualMachines/read",)
        required += tuple(spec["resource_type"] + "/read" for spec in services.values())
        if "tcp" in kinds:
            required += ("Microsoft.Network/networkWatchers/connectivityCheck/action",)
        if "route" in kinds:
            required += ("Microsoft.Network/networkWatchers/nextHop/action",)
        if kinds & {"dns_private", "egress_ip", "http"} or fixtures:
            required += ("Microsoft.Compute/virtualMachines/runCommand/action",)
        if fixtures:
            required += (
                "Microsoft.Compute/virtualMachines/write",
                "Microsoft.Network/networkInterfaces/write",
                "Microsoft.Network/networkInterfaces/read",
                "Microsoft.Network/networkInterfaces/join/action",
                "Microsoft.Network/virtualNetworks/read",
                "Microsoft.Network/virtualNetworks/subnets/read",
                "Microsoft.Network/virtualNetworks/subnets/join/action",
            )
            if any(isinstance(s, dict) and s.get("public_ip") is True
                   for s in sources.values()):
                required += (
                    "Microsoft.Network/publicIPAddresses/read",
                    "Microsoft.Network/publicIPAddresses/write",
                    "Microsoft.Network/publicIPAddresses/join/action",
                )
        if any(isinstance(s, str) for s in sources.values()):
            required += ("Microsoft.Network/networkInterfaces/read",)
        if isinstance(bindings.get("expected_egress_ip"), dict):
            required += (
                "Microsoft.Network/natGateways/read",
                "Microsoft.Network/azureFirewalls/read",
                "Microsoft.Network/publicIPAddresses/read",
            )
        destinations = bindings.get("destinations", {})
        if isinstance(destinations, dict) and any(
            isinstance(d, dict) and "public_ip" in d for d in destinations.values()
        ):
            required += ("Microsoft.Network/publicIPAddresses/read",)
        dns_bindings = bindings.get("dns_private_addresses", {})
        if isinstance(dns_bindings, dict) and any(
            isinstance(value, dict) for value in dns_bindings.values()
        ):
            required += (
                "Microsoft.Network/privateEndpoints/read",
                "Microsoft.Network/networkInterfaces/read",
            )
        routes = bindings.get("route_destinations", {})
        if isinstance(routes, dict) and any(
            isinstance(route, dict) and isinstance(route.get("next_hop_ip"), dict)
            for route in routes.values()
        ):
            required += ("Microsoft.Network/azureFirewalls/read",)
        for action in required:
            if not any(
                isinstance(p, dict)
                and isinstance(p.get("actions"), list)
                and isinstance(p.get("notActions", []), list)
                and any(isinstance(a, str) and fnmatch.fnmatchcase(action.lower(), a.lower())
                        for a in p["actions"])
                and not any(isinstance(a, str) and fnmatch.fnmatchcase(action.lower(), a.lower())
                            for a in p.get("notActions", []))
                for p in permissions["value"]
            ):
                raise _Blocked("missing_subscription_capability")

    def _fixtures(self, result, original, group, run_id, directory, scenario_id):
        bindings = {key: copy.deepcopy(value) for key, value in original.items()
                    if not key.startswith("_")}
        bindings["_blocked_sources"] = {}
        bindings["_blocked_destinations"] = {}
        bindings["_fixture_roles"] = set()
        bindings["_http_markers"] = {}
        bindings["_requested_http_markers"] = set()
        bindings["_ready_http_markers"] = set()
        bindings["_public_source_ips"] = {}
        bindings["_dns_errors"] = {}
        bindings["_route_errors"] = {}
        sources = bindings.setdefault("sources", {})
        source_ips = bindings.setdefault("source_ips", {})
        destinations = bindings.setdefault("destinations", {})
        if not all(isinstance(v, dict) for v in (sources, source_ips, destinations)):
            raise _Blocked("invalid_bindings")
        fixture_roles = set()
        key_path = directory.resolve() / f"study-cloud-{run_id}" / "probe_ed25519"
        for index, (role, spec) in enumerate(list(sources.items())):
            try:
                if isinstance(spec, str):
                    match = _VM_ID.fullmatch(spec)
                    if not match or match[1].lower() != self.config.subscription_id.lower():
                        raise _Blocked("explicit_source_vm_required")
                    vm = self._az(result, "external_source_inspect", [
                        "vm", "show", "--ids", spec,
                        "--query", "{id:id,networkProfile:networkProfile}",
                    ])
                    if not isinstance(vm, dict) or str(vm.get("id", "")).lower() != spec.lower():
                        raise _Blocked("source_vm_identity_mismatch")
                    self._external_source_network(result, vm, group)
                    continue
                self._validate_fixture_spec(spec, role, scenario_id)
                public = spec.get("public_ip", False)
                root = f"/subscriptions/{self.config.subscription_id}/resourceGroups/{group}"
                vnet_id = root + f"/providers/Microsoft.Network/virtualNetworks/{spec['vnet']}"
                subnet_id = vnet_id + f"/subnets/{spec['subnet']}"
                vnet = self._az(result, "fixture_vnet_inspect", [
                    "network", "vnet", "show", "--resource-group", group,
                    "--name", spec["vnet"], "--query", "{id:id,location:location}",
                ])
                if not isinstance(vnet, dict) or (
                    str(vnet.get("id", "")).lower() != vnet_id.lower()
                    or not isinstance(vnet.get("location"), str)
                    or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{1,63}", vnet["location"])
                    or spec.get("location", vnet["location"]).lower() != vnet["location"].lower()
                ):
                    raise _Blocked("candidate_vnet_identity_mismatch")
                subnet = self._az(result, "fixture_subnet_inspect", [
                    "network", "vnet", "subnet", "show", "--resource-group", group,
                    "--vnet-name", spec["vnet"], "--name", spec["subnet"],
                    "--query", "{id:id,addressPrefix:addressPrefix,addressPrefixes:addressPrefixes}",
                ])
                if not isinstance(subnet, dict) or str(subnet.get("id", "")).lower() != subnet_id.lower():
                    raise _Blocked("candidate_subnet_identity_mismatch")
                requested_ip = None
                private_args = []
                if "private_ip_address" in spec:
                    requested_ip = self._ip(spec["private_ip_address"])
                    prefixes = subnet.get("addressPrefixes") or []
                    if not isinstance(prefixes, list):
                        raise _Blocked("candidate_subnet_prefix_required")
                    if subnet.get("addressPrefix"):
                        prefixes = [*prefixes, subnet["addressPrefix"]]
                    if not prefixes or any(not isinstance(p, str) for p in prefixes):
                        raise _Blocked("candidate_subnet_prefix_required")
                    networks = [ipaddress.ip_network(p) for p in prefixes]
                    if not any(
                        requested_ip.version == network.version and requested_ip in network
                        and int(requested_ip) - int(network.network_address) >= 4
                        and requested_ip != network.broadcast_address
                        for network in networks
                    ):
                        raise _Blocked("fixture_ip_outside_subnet_or_azure_reserved")
                    private_args = ["--private-ip-address", str(requested_ip)]
                if not key_path.with_suffix(".pub").exists():
                    if key_path.exists() or key_path.is_symlink() or key_path.with_suffix(".pub").is_symlink():
                        raise _Blocked("fixture_key_path_already_exists")
                    key_path.parent.mkdir(parents=True, exist_ok=True)
                    entry = {"operation": "fixture_ssh_keygen", "status": "blocked"}
                    result["operations"].append(entry)
                    key_cleanup_failed = False
                    try:
                        keygen = self.command_runner(
                            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "",
                             "-f", str(key_path)],
                            capture_output=True, text=True, shell=False, timeout=30,
                        )
                        if keygen.returncode or not key_path.is_file() or not key_path.with_suffix(".pub").is_file():
                            raise _Blocked("fixture_key_generation_failed")
                        entry["status"] = "passed"
                    except (OSError, subprocess.TimeoutExpired):
                        raise _Blocked("fixture_key_generation_failed") from None
                    finally:
                        cleanup_entry = {
                            "operation": "fixture_private_key_cleanup", "status": "blocked",
                        }
                        result["operations"].append(cleanup_entry)
                        try:
                            key_path.unlink(missing_ok=True)
                            cleanup_entry["status"] = "passed"
                        except OSError:
                            cleanup_entry["reason"] = "fixture_private_key_removal_failed"
                            key_cleanup_failed = True
                    if key_cleanup_failed:
                        raise _Blocked("fixture_private_key_removal_failed")
                name = f"study-probe-{run_id[:12]}-{index}"
                nic_id = root + f"/providers/Microsoft.Network/networkInterfaces/{name}-nic"
                public_id = None
                public_args = []
                if public:
                    public_name = f"{name}-pip"
                    public_id = root + f"/providers/Microsoft.Network/publicIPAddresses/{public_name}"
                    self._az(result, "fixture_public_ip_create", [
                        "network", "public-ip", "create", "--resource-group", group,
                        "--name", public_name, "--location", vnet["location"],
                        "--sku", "Standard", "--allocation-method", "Static",
                        "--version", "IPv4",
                    ])
                    bindings["_public_source_ips"][role] = self._public_ip(
                        result, public_name, group
                    )
                    public_args = ["--public-ip-address", public_id]
                self._az(result, "fixture_nic_create", [
                    "network", "nic", "create", "--resource-group", group,
                    "--name", f"{name}-nic", "--subnet", subnet_id,
                    "--location", vnet["location"], *public_args, *private_args,
                ])
                nic = self._az(result, "fixture_nic_inspect", [
                    "network", "nic", "show", "--ids", nic_id,
                ])
                if not isinstance(nic, dict) or (
                    str(nic.get("id", "")).lower() != nic_id.lower()
                    or nic.get("networkSecurityGroup") is not None
                    or not isinstance(nic.get("ipConfigurations"), list)
                    or len(nic["ipConfigurations"]) != 1
                ):
                    raise _Blocked("fixture_nic_not_isolated")
                ip_config = nic["ipConfigurations"][0]
                if not isinstance(ip_config, dict) or (
                    (ip_config.get("publicIPAddress") is not None if not public else
                     not isinstance(ip_config.get("publicIPAddress"), dict)
                     or str(ip_config["publicIPAddress"].get("id", "")).lower() != public_id.lower())
                    or not isinstance(ip_config.get("subnet"), dict)
                    or str(ip_config["subnet"].get("id", "")).lower() != subnet_id.lower()
                ):
                    raise _Blocked("fixture_nic_not_isolated")
                private_ip = self._ip(ip_config.get("privateIPAddress"))
                if requested_ip is not None and private_ip != requested_ip:
                    raise _Blocked("fixture_static_ip_not_honored")
                if not private_ip.is_private or private_ip.is_loopback or private_ip.is_unspecified:
                    raise _Blocked("fixture_private_ip_required")
                vm_id = root + f"/providers/Microsoft.Compute/virtualMachines/{name}"
                vm = self._az(result, "fixture_vm_create", [
                    "vm", "create", "--resource-group", group, "--name", name,
                    "--location", vnet["location"], "--image", "Ubuntu2204",
                    "--size", spec["vm_size"], "--admin-username", "studyprobe",
                    "--ssh-key-values", str(key_path.with_suffix(".pub")), "--nics", nic_id,
                    "--query", "{id:id}",
                ], timeout=_DEPLOY_TIMEOUT)
                if not isinstance(vm, dict) or str(vm.get("id", "")).lower() != vm_id.lower():
                    raise _Blocked("fixture_vm_identity_mismatch")
                health = self._az(result, "fixture_agent_health", [
                    "vm", "run-command", "invoke", "--ids", vm_id,
                    "--command-id", "RunShellScript", "--scripts",
                    "python3 -c 'import json; print(json.dumps({\"ready\": True}))'",
                ])
                health_result = self._machine_result(health)
                if set(health_result) != {"ready"} or health_result["ready"] is not True:
                    raise _Blocked("fixture_agent_not_ready")
                sources[role] = vm_id
                source_ips[role] = str(private_ip)
                fixture_roles.add(role)
            except _Blocked as exc:
                bindings["_blocked_sources"][role] = str(exc)
            except (ValueError, TypeError, KeyError, AttributeError, OSError):
                bindings["_blocked_sources"][role] = "invalid_fixture_data"
        for role, spec in list(destinations.items()):
            try:
                if not isinstance(spec, dict):
                    destinations[role] = self._destination(
                        self._expand(spec, run_id, group)
                    )
                    continue
                marker = spec.get("expected_body")
                if marker is not None:
                    marker = self._expand(marker, run_id, group)
                    if not isinstance(marker, str) or not re.fullmatch(
                        r"[A-Za-z0-9_.-]{8,256}", marker
                    ) or run_id not in marker:
                        raise _Blocked("unique_http_marker_required")
                    bindings["_http_markers"][role] = marker
                    if "source" in spec:
                        bindings["_requested_http_markers"].add(marker)
                if "address" in spec and not set(spec) - {"address", "expected_body"}:
                    destinations[role] = self._destination(self._expand(spec["address"], run_id, group))
                    continue
                if "public_ip" in spec and not set(spec) - {"public_ip", "expected_body"}:
                    destinations[role] = self._public_ip(
                        result, self._expand(spec["public_ip"], run_id, group), group
                    )
                    continue
                if set(spec) - {"source", "listener_ports", "expected_body", "address_kind"} or not isinstance(spec.get("source"), str):
                    raise _Blocked("invalid_destination_binding")
                source_role = spec["source"]
                if source_role not in sources or source_role in bindings["_blocked_sources"]:
                    raise _Blocked("destination_fixture_unavailable")
                address_kind = spec.get("address_kind", "private")
                if address_kind not in {"private", "public"}:
                    raise _Blocked("invalid_destination_address_kind")
                addresses = bindings["_public_source_ips"] if address_kind == "public" else source_ips
                destinations[role] = self._destination(addresses.get(source_role))
                ports = spec.get("listener_ports", [])
                if not isinstance(ports, list) or any(
                    type(p) is not int or not 1 <= p <= 65535 for p in ports
                ) or len(set(ports)) != len(ports):
                    raise _Blocked("invalid_listener_ports")
                if ports:
                    if source_role not in fixture_roles:
                        raise _Blocked("listeners_require_owned_fixture")
                    script = _LISTENER_SCRIPT
                    if marker:
                        script = _HTTP_LISTENER_SCRIPT.replace(
                            "BODY_LENGTH", str(len(marker))
                        ).replace("BODY_MARKER", marker)
                    data = self._az(result, "fixture_listener_start", [
                        "vm", "run-command", "invoke", "--ids", sources[source_role],
                        "--command-id", "RunShellScript", "--scripts",
                        script.replace("PORTS", repr(ports)),
                    ])
                    observed = self._machine_result(data)
                    if (observed != {"listener_ports": ports}
                            or not all(type(p) is int for p in observed["listener_ports"])):
                        raise _Blocked("fixture_listener_not_ready")
                    if marker:
                        bindings["_ready_http_markers"].add(marker)
            except _Blocked as exc:
                bindings["_blocked_destinations"][role] = str(exc)
            except (ValueError, TypeError, KeyError, AttributeError):
                bindings["_blocked_destinations"][role] = "invalid_destination_binding"
        bindings["_fixture_roles"] = fixture_roles
        if isinstance(bindings.get("expected_egress_ip"), dict):
            try:
                bindings["expected_egress_ip"] = self._egress_resource_ip(
                    result, bindings["expected_egress_ip"], group
                )
            except _Blocked as exc:
                bindings["_egress_error"] = str(exc)
            except (ValueError, TypeError, KeyError, AttributeError):
                bindings["_egress_error"] = "invalid_egress_resource"
        dns_bindings = bindings.get("dns_private_addresses", {})
        if isinstance(dns_bindings, dict):
            for role, spec in list(dns_bindings.items()):
                if not isinstance(spec, dict):
                    continue
                try:
                    name = self._private_endpoint_name(spec, run_id, group)
                    dns_bindings[role] = self._private_endpoint_ips(result, name, group)
                except _Blocked as exc:
                    bindings["_dns_errors"][role] = str(exc)
                except (ValueError, TypeError, KeyError, AttributeError):
                    bindings["_dns_errors"][role] = "invalid_private_endpoint_data"
        routes = bindings.get("route_destinations", {})
        if isinstance(routes, dict):
            for role, spec in routes.items():
                if not isinstance(spec, dict) or not isinstance(spec.get("next_hop_ip"), dict):
                    continue
                try:
                    if spec.get("next_hop_type", "VirtualAppliance") != "VirtualAppliance":
                        raise _Blocked("firewall_route_requires_virtual_appliance")
                    name = self._firewall_route_name(spec["next_hop_ip"], run_id, group)
                    spec["next_hop_ip"] = self._firewall_private_ip(result, name, group)
                except _Blocked as exc:
                    bindings["_route_errors"][role] = str(exc)
                except (ValueError, TypeError, KeyError, AttributeError):
                    bindings["_route_errors"][role] = "invalid_firewall_route_data"
        return bindings

    def _firewall_route_name(self, spec, run_id, group):
        if set(spec) != {"firewall"}:
            raise _Blocked("invalid_firewall_route_binding")
        name = self._expand(spec["firewall"], run_id, group)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", name):
            raise _Blocked("invalid_firewall_route_name")
        return name

    def _firewall_private_ip(self, result, name, group):
        root = f"/subscriptions/{self.config.subscription_id}/resourceGroups/{group}"
        expected_id = root + f"/providers/Microsoft.Network/azureFirewalls/{name}"
        firewall = self._az(result, "route_firewall_inspect", [
            "network", "firewall", "show", "--resource-group", group, "--name", name,
        ])
        if not isinstance(firewall, dict) or (
            str(firewall.get("id", "")).lower() != expected_id.lower()
            or not isinstance(firewall.get("ipConfigurations"), list)
            or not firewall["ipConfigurations"]
        ):
            raise _Blocked("firewall_route_identity_or_ip_missing")
        addresses = set()
        for config in firewall["ipConfigurations"]:
            subnet = config.get("subnet") if isinstance(config, dict) else None
            subnet_id = subnet.get("id") if isinstance(subnet, dict) else None
            if not isinstance(subnet_id, str) or not re.fullmatch(
                re.escape(root + "/providers/Microsoft.Network/virtualNetworks/")
                + r"[^/]+/subnets/AzureFirewallSubnet", subnet_id, re.I
            ):
                raise _Blocked("firewall_route_subnet_identity_mismatch")
            ip = self._ip(config.get("privateIPAddress"))
            if not ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
                raise _Blocked("firewall_route_private_ip_required")
            addresses.add(str(ip))
        if len(addresses) != 1:
            raise _Blocked("single_firewall_route_ip_required")
        return next(iter(addresses))

    def _private_endpoint_name(self, spec, run_id, group):
        if set(spec) != {"private_endpoint"}:
            raise _Blocked("invalid_private_endpoint_binding")
        name = self._expand(spec["private_endpoint"], run_id, group)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", name):
            raise _Blocked("invalid_private_endpoint_name")
        return name

    def _private_endpoint_ips(self, result, name, group):
        root = f"/subscriptions/{self.config.subscription_id}/resourceGroups/{group}"
        endpoint_id = root + f"/providers/Microsoft.Network/privateEndpoints/{name}"
        endpoint = self._az(result, "dns_private_endpoint_inspect", [
            "network", "private-endpoint", "show", "--resource-group", group, "--name", name,
        ])
        if not isinstance(endpoint, dict) or str(endpoint.get("id", "")).lower() != endpoint_id.lower():
            raise _Blocked("private_endpoint_identity_mismatch")
        self._guard_ids(endpoint)
        connections = endpoint.get("privateLinkServiceConnections", [])
        manual = endpoint.get("manualPrivateLinkServiceConnections", [])
        if not isinstance(connections, list) or not isinstance(manual, list) or not connections + manual:
            raise _Blocked("private_endpoint_connection_not_approved")
        if any(not isinstance(c, dict)
               or not isinstance(c.get("privateLinkServiceConnectionState"), dict)
               or c["privateLinkServiceConnectionState"].get("status") != "Approved"
               for c in connections + manual):
            raise _Blocked("private_endpoint_connection_not_approved")
        subnet = endpoint.get("subnet")
        subnet_id = subnet.get("id") if isinstance(subnet, dict) else None
        if not isinstance(subnet_id, str) or not re.fullmatch(
            re.escape(root + "/providers/Microsoft.Network/virtualNetworks/")
            + r"[^/]+/subnets/[^/]+", subnet_id, re.I
        ):
            raise _Blocked("private_endpoint_subnet_identity_mismatch")
        references = endpoint.get("networkInterfaces")
        if not isinstance(references, list) or not references:
            raise _Blocked("private_endpoint_nic_missing")
        addresses = set()
        for reference in references:
            nic_id = reference.get("id") if isinstance(reference, dict) else None
            if not isinstance(nic_id, str) or not re.fullmatch(
                re.escape(root + "/providers/Microsoft.Network/networkInterfaces/")
                + r"[^/]+", nic_id, re.I
            ):
                raise _Blocked("private_endpoint_nic_identity_mismatch")
            nic = self._az(result, "dns_private_endpoint_nic_inspect", [
                "network", "nic", "show", "--ids", nic_id,
            ])
            if not isinstance(nic, dict) or (
                str(nic.get("id", "")).lower() != nic_id.lower()
                or not isinstance(nic.get("privateEndpoint"), dict)
                or str(nic["privateEndpoint"].get("id", "")).lower() != endpoint_id.lower()
                or not isinstance(nic.get("ipConfigurations"), list)
                or not nic["ipConfigurations"]
            ):
                raise _Blocked("private_endpoint_nic_identity_mismatch")
            for config in nic["ipConfigurations"]:
                if not isinstance(config, dict) or (
                    config.get("publicIPAddress") is not None
                    or not isinstance(config.get("subnet"), dict)
                    or str(config["subnet"].get("id", "")).lower() != subnet_id.lower()
                ):
                    raise _Blocked("private_endpoint_nic_subnet_mismatch")
                ip = self._ip(config.get("privateIPAddress"))
                if not ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
                    raise _Blocked("private_endpoint_private_ip_required")
                addresses.add(str(ip))
        if not addresses:
            raise _Blocked("private_endpoint_ip_missing")
        return sorted(addresses)

    def _external_source_network(self, result, vm, group):
        profile = vm.get("networkProfile")
        if not isinstance(profile, dict) or (
            not isinstance(profile.get("networkInterfaces"), list)
            or not profile["networkInterfaces"]
        ):
            raise _Blocked("external_source_network_not_verified")
        for reference in profile["networkInterfaces"]:
            nic_id = reference.get("id") if isinstance(reference, dict) else None
            if not isinstance(nic_id, str) or not re.fullmatch(
                rf"/subscriptions/{re.escape(self.config.subscription_id)}/resourceGroups/[^/]+"
                r"/providers/Microsoft.Network/networkInterfaces/[^/]+", nic_id, re.I
            ):
                raise _Blocked("external_source_network_not_verified")
            nic = self._az(result, "external_source_nic_inspect", [
                "network", "nic", "show", "--ids", nic_id,
            ])
            if not isinstance(nic, dict) or (
                str(nic.get("id", "")).lower() != nic_id.lower()
                or not isinstance(nic.get("ipConfigurations"), list)
                or not nic["ipConfigurations"]
            ):
                raise _Blocked("external_source_network_not_verified")
            for config in nic["ipConfigurations"]:
                subnet = config.get("subnet") if isinstance(config, dict) else None
                subnet_id = subnet.get("id") if isinstance(subnet, dict) else None
                match = re.fullmatch(
                    rf"/subscriptions/{re.escape(self.config.subscription_id)}/resourceGroups/([^/]+)"
                    r"/providers/Microsoft.Network/virtualNetworks/[^/]+/subnets/[^/]+",
                    subnet_id, re.I,
                ) if isinstance(subnet_id, str) else None
                if not match or match[1].lower() == group.lower():
                    raise _Blocked("external_source_must_be_outside_candidate_network")

    @staticmethod
    def _expand(value, run_id, group):
        if not isinstance(value, str):
            raise _Blocked("invalid_destination_binding")
        return value.replace("{study_suffix}", run_id).replace("{resource_group}", group)

    def _public_ip(self, result, name, group):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", name):
            raise _Blocked("invalid_public_ip_name")
        public_id = (
            f"/subscriptions/{self.config.subscription_id}/resourceGroups/{group}"
            f"/providers/Microsoft.Network/publicIPAddresses/{name}"
        )
        public = self._az(result, "candidate_public_ip_inspect", [
            "network", "public-ip", "show", "--ids", public_id,
            "--query", "{id:id,ipAddress:ipAddress}",
        ])
        if not isinstance(public, dict) or str(public.get("id", "")).lower() != public_id.lower():
            raise _Blocked("candidate_public_ip_identity_mismatch")
        return str(self._ip(public.get("ipAddress")))

    def _egress_resource_ip(self, result, spec, group):
        if set(spec) != {"resource_type", "name"} or (
            spec["resource_type"] not in {"nat_gateway", "firewall"}
            or not isinstance(spec["name"], str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", spec["name"])
        ):
            raise _Blocked("invalid_egress_resource")
        nat = spec["resource_type"] == "nat_gateway"
        data = self._az(result, "egress_resource_inspect", [
            "network", "nat" if nat else "firewall", *(["gateway"] if nat else []),
            "show", "--resource-group", group, "--name", spec["name"],
        ])
        root = f"/subscriptions/{self.config.subscription_id}/resourceGroups/{group}"
        expected_id = root + "/providers/Microsoft.Network/" + (
            "natGateways/" if nat else "azureFirewalls/"
        ) + spec["name"]
        if not isinstance(data, dict) or str(data.get("id", "")).lower() != expected_id.lower():
            raise _Blocked("egress_resource_identity_mismatch")
        if nat:
            ips = data.get("publicIpAddresses", [])
            if data.get("publicIpPrefixes"):
                raise _Blocked("multiple_egress_ips_unsupported")
        else:
            configs = data.get("ipConfigurations", [])
            if not isinstance(configs, list):
                raise _Blocked("invalid_egress_resource")
            ips = [c.get("publicIPAddress") for c in configs if isinstance(c, dict)
                   and c.get("publicIPAddress")]
        if not isinstance(ips, list) or len(ips) != 1 or not isinstance(ips[0], dict):
            raise _Blocked("single_egress_ip_required")
        public_id = ips[0].get("id")
        if not isinstance(public_id, str) or not re.fullmatch(
            re.escape(root + "/providers/Microsoft.Network/publicIPAddresses/")
            + r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", public_id, re.I
        ):
            raise _Blocked("egress_public_ip_identity_mismatch")
        public = self._az(result, "egress_public_ip_inspect", [
            "network", "public-ip", "show", "--ids", public_id,
            "--query", "{id:id,ipAddress:ipAddress}",
        ])
        if not isinstance(public, dict) or str(public.get("id", "")).lower() != public_id.lower():
            raise _Blocked("egress_public_ip_identity_mismatch")
        return str(self._ip(public.get("ipAddress")))

    def _owned_group(self, group, name, run_id):
        expected_id = f"/subscriptions/{self.config.subscription_id}/resourceGroups/{name}"
        if not isinstance(group, dict) or (
            group.get("name") != name
            or str(group.get("id", "")).lower() != expected_id.lower()
            or not isinstance(group.get("tags"), dict)
            or group["tags"].get(_OWNER_TAG) != run_id
        ):
            raise _Blocked("resource_group_ownership_not_verified")

    @staticmethod
    def _validate_check(check, seen, duplicate_ids):
        if not isinstance(check, dict) or (
            not isinstance(check.get("id"), str) or not check["id"].strip()
            or check["id"] in duplicate_ids or check["id"] in seen
            or check.get("kind") not in {
                "tcp", "http", "egress_ip", "dns_private", "route", "public_access_disabled",
            }
            or any(not isinstance(check.get(role), str) or not check[role]
                   for role in ("source", "destination"))
            or type(check.get("expected", True)) is not bool
        ):
            raise _Blocked("invalid_runtime_check")
        seen.add(check["id"])
        if check["kind"] == "public_access_disabled" and (
            check["source"] != "control-plane" or check["destination"] not in _SERVICE_TYPES
        ):
            raise _Blocked("invalid_control_plane_check")
        if check["kind"] in {"tcp", "http"} and (
            type(check.get("port")) is not int or not 1 <= check["port"] <= 65535
        ):
            raise _Blocked("invalid_probe_port")

    @staticmethod
    def _ip(value):
        if not isinstance(value, str):
            raise _Blocked("invalid_ip_address")
        return ipaddress.ip_address(value)

    @staticmethod
    def _destination(value):
        if not isinstance(value, str) or not value or len(value) > 253:
            raise _Blocked("invalid_destination")
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            if not re.fullmatch(
                r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?", value
            ):
                raise _Blocked("invalid_destination") from None
        return value

    def _probe(self, result, check, bindings):
        if check["kind"] == "public_access_disabled":
            services = bindings.get("service_resources", {})
            if not isinstance(services, dict):
                raise _Blocked("invalid_service_resources")
            role = check["destination"]
            spec = services.get(role)
            name = self._service_name(
                role, spec, result["study_suffix"], result["resource_group"]
            )
            resource_id = (
                f"/subscriptions/{self.config.subscription_id}/resourceGroups/"
                f"{result['resource_group']}/providers/{_SERVICE_TYPES[role]}/{name}"
            )
            observed = self._az(result, "observe_public_network_access", [
                "resource", "show", "--ids", resource_id,
                "--query", "{id:id,publicNetworkAccess:properties.publicNetworkAccess}",
            ])
            if not isinstance(observed, dict) or (
                str(observed.get("id", "")).lower() != resource_id.lower()
                or observed.get("publicNetworkAccess") not in {"Enabled", "Disabled"}
            ):
                raise _Blocked("invalid_public_network_access_observation")
            return observed["publicNetworkAccess"] == "Disabled"
        if check["source"] in bindings.get("_blocked_sources", {}):
            raise _Blocked(bindings["_blocked_sources"][check["source"]])
        source = bindings.get("sources", {}).get(check["source"])
        match = _VM_ID.fullmatch(source) if isinstance(source, str) else None
        if not match or match[1].lower() != self.config.subscription_id.lower():
            raise _Blocked("explicit_source_vm_required")
        # Resource IDs are passed as individual argv values, never shell input.
        if check["destination"] in bindings.get("_blocked_destinations", {}):
            raise _Blocked(bindings["_blocked_destinations"][check["destination"]])
        destination = self._destination(bindings.get("destinations", {}).get(check["destination"]))
        kind = check["kind"]
        if kind == "http":
            if check["source"] in bindings.get("_fixture_roles", set()):
                raise _Blocked("explicit_external_http_source_required")
            marker = bindings.get("_http_markers", {}).get(check["destination"])
            if not marker:
                raise _Blocked("unique_http_marker_required")
            if (marker in bindings.get("_requested_http_markers", set())
                    and marker not in bindings.get("_ready_http_markers", set())):
                raise _Blocked("http_listener_fixture_not_ready")
            host = f"[{destination}]" if ":" in destination else destination
            url = f"http://{host}:{check['port']}/"
            data = self._az(result, "probe_http", [
                "vm", "run-command", "invoke", "--ids", source,
                "--command-id", "RunShellScript", "--scripts",
                _HTTP_SCRIPT.replace("URL", repr(url)),
            ])
            observed = self._machine_result(data)
            if (type(observed.get("status")) is not int
                    or not 200 <= observed["status"] < 300
                    or not isinstance(observed.get("body"), str)
                    or len(observed["body"]) > 4096):
                raise _Blocked("invalid_http_result")
            return observed["body"] == marker
        if kind == "tcp":
            data = self._az(result, "probe_tcp", [
                "network", "watcher", "test-connectivity", "--source-resource", source,
                "--dest-address", destination, "--dest-port", str(check["port"]),
                "--protocol", "Tcp",
            ])
            if not isinstance(data, dict) or data.get("connectionStatus") not in {
                "Reachable", "Unreachable",
            }:
                raise _Blocked("invalid_connectivity_result")
            # A negative claim needs actual completed probes, not all-lost timeout.
            sent, failed = data.get("probesSent"), data.get("probesFailed")
            if type(sent) is not int or type(failed) is not int or not 0 <= failed <= sent or sent <= 0:
                raise _Blocked("missing_connectivity_probes")
            if data["connectionStatus"] == "Reachable":
                if failed == sent:
                    raise _Blocked("inconsistent_connectivity_result")
                return True
            hops = data.get("hops", [])
            issues = [
                issue for hop in hops if isinstance(hop, dict)
                for issue in hop.get("issues", []) if isinstance(issue, dict)
            ] if isinstance(hops, list) else []
            if failed != sent or not any(
                issue.get("type") == "NetworkSecurityRule"
                and issue.get("origin") in {"Inbound", "Outbound"}
                and issue.get("severity") == "Error"
                for issue in issues
            ):
                raise _Blocked("unreachable_without_explicit_deny_evidence")
            return False
        if kind == "route":
            if check["destination"] in bindings.get("_route_errors", {}):
                raise _Blocked(bindings["_route_errors"][check["destination"]])
            source_ip = str(self._ip(
                bindings.get("source_ips", {}).get(check["source"])
            ))
            ipaddress.ip_address(destination)
            expected = copy.deepcopy(bindings.get("route_destinations", {}).get(check["destination"]))
            declared_type = check.get("expected_next_hop_type")
            if declared_type is not None:
                if declared_type not in _NEXT_HOPS or not isinstance(expected, dict):
                    raise _Blocked("explicit_route_expectation_required")
                if expected.get("next_hop_type", declared_type) != declared_type:
                    raise _Blocked("conflicting_route_expectation")
                expected["next_hop_type"] = declared_type
            if not isinstance(expected, dict) or (
                expected.get("next_hop_type") not in _NEXT_HOPS
            ):
                raise _Blocked("explicit_route_expectation_required")
            if expected["next_hop_type"] == "None" and expected.get("next_hop_ip") in (None, "", "0.0.0.0"):
                expected["next_hop_ip"] = ""
            if not isinstance(expected.get("next_hop_ip"), str):
                raise _Blocked("explicit_route_expectation_required")
            if expected["next_hop_ip"]:
                expected["next_hop_ip"] = str(self._ip(expected["next_hop_ip"]))
            elif expected["next_hop_type"] == "VirtualAppliance":
                raise _Blocked("explicit_route_expectation_required")
            data = self._az(result, "probe_route", [
                "network", "watcher", "show-next-hop", "--vm", source,
                "--resource-group", match[2], "--source-ip", source_ip,
                "--dest-ip", destination,
            ])
            if not isinstance(data, dict) or (
                data.get("nextHopType") not in _NEXT_HOPS
                or "nextHopIpAddress" not in data
            ):
                raise _Blocked("invalid_route_result")
            if data["nextHopType"] == "None" and data.get("nextHopIpAddress") in (None, "", "0.0.0.0"):
                data["nextHopIpAddress"] = ""
            if not isinstance(data["nextHopIpAddress"], str):
                raise _Blocked("invalid_route_result")
            if data["nextHopIpAddress"]:
                data["nextHopIpAddress"] = str(self._ip(data["nextHopIpAddress"]))
            elif data["nextHopType"] == "VirtualAppliance":
                raise _Blocked("invalid_route_result")
            return (data["nextHopType"] == expected["next_hop_type"]
                    and data["nextHopIpAddress"] == expected["next_hop_ip"])
        if kind == "egress_ip":
            if bindings.get("_egress_error"):
                raise _Blocked(bindings["_egress_error"])
            if destination != "api.ipify.org":
                raise _Blocked("unsupported_egress_endpoint")
            expected_ip = self._ip(bindings.get("expected_egress_ip"))
            script = _EGRESS_SCRIPT
        else:
            if check["destination"] in bindings.get("_dns_errors", {}):
                raise _Blocked(bindings["_dns_errors"][check["destination"]])
            expected_addresses = bindings.get("dns_private_addresses", {}).get(check["destination"])
            if not isinstance(expected_addresses, list) or not expected_addresses:
                raise _Blocked("explicit_private_addresses_required")
            expected_ips = {self._ip(ip) for ip in expected_addresses}
            if any(not ip.is_private or ip.is_loopback or ip.is_link_local
                   or ip.is_unspecified or ip.is_multicast for ip in expected_ips):
                raise _Blocked("invalid_private_addresses")
            script = _DNS_SCRIPT.replace("HOST", repr(destination))
        data = self._az(result, f"probe_{kind}", [
            "vm", "run-command", "invoke", "--ids", source,
            "--command-id", "RunShellScript", "--scripts", script,
        ])
        observed = self._machine_result(data)
        if kind == "egress_ip":
            return self._ip(observed.get("egress_ip")) == expected_ip
        addresses = observed.get("addresses")
        if not isinstance(addresses, list) or not addresses:
            raise _Blocked("missing_dns_observation")
        return {self._ip(ip) for ip in addresses} == expected_ips

    def _service_name(self, role, spec, run_id, group):
        if role not in _SERVICE_TYPES or not isinstance(spec, dict) or (
            set(spec) != {"resource_type", "name"}
            or spec.get("resource_type") != _SERVICE_TYPES[role]
        ):
            raise _Blocked("invalid_service_resource_binding")
        name = self._expand(spec["name"], run_id, group)
        maximum = 63 if role == "sql" else 50
        if not 3 <= len(name) <= maximum or not re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", name
        ):
            raise _Blocked("invalid_service_resource_name")
        return name

    @staticmethod
    def _machine_result(data):
        if not isinstance(data, dict) or not isinstance(data.get("value"), list):
            raise _Blocked("invalid_run_command_result")
        stdout = []
        for item in data["value"]:
            if not isinstance(item, dict) or not isinstance(item.get("code"), str):
                raise _Blocked("invalid_run_command_result")
            if item["code"] == "ComponentStatus/StdOut/succeeded":
                stdout.append(item.get("message"))
            elif item["code"] != "ComponentStatus/StdErr/succeeded" or item.get("message", "").strip():
                raise _Blocked("run_command_error")
        if len(stdout) != 1 or not isinstance(stdout[0], str):
            raise _Blocked("missing_machine_probe_result")
        observed = _json_loads(stdout[0])
        if not isinstance(observed, dict):
            raise _Blocked("invalid_machine_probe_result")
        return observed
