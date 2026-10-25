# Azure Network Rego Policies

These Conftest policies evaluate ARM JSON produced by `bicep build`. They
currently require a VNet, a non-empty address-prefix list, at least one subnet,
and an `Experiment` tag. They also reject NSG rules that allow public inbound
SSH/RDP or wildcard destination ports.

This is an initial policy set, not complete scenario acceptance. CIDR overlap,
subnet containment, private-endpoint requirements, and scenario-specific
connectivity are not yet covered.

Subnet presence accepts inline declarations and literal child-resource names.
For ARM expression-based names, this coarse policy defers association to the
independent structural evaluator rather than rejecting an equivalent Bicep
representation. A policy pass alone never proves correct parent association.

## Validate a Bicep Template

```powershell
$iteration = 'results\live\<run-id>\scenarios\NET-01\B1\iteration-01'
bicep build "$iteration\template.bicep" --outfile "$env:TEMP\net-01.json"
conftest test "$env:TEMP\net-01.json" --policy policies\azure --output json
```

Replace `<run-id>` with an actual experiment run. There are no bundled B0
templates; generated files are experiment evidence, not reference solutions.

## Run Rego Unit Tests

OPA tests are kept outside the Conftest policy directory so Conftest loads only
production rules:

```powershell
opa test policies/azure tests/rego -v
```

The installed Conftest bundles OPA and can run the same suites without a
separate `opa` executable:

```powershell
& "$HOME\.local\bin\conftest.exe" verify --policy policies\azure --policy tests\rego
```

The Bicep fixture under `tests/fixtures/` is only a deterministic validator
regression input. It is not a B0 baseline or generated experimental evidence.

## Reference Repositories

- [Conftest examples](https://github.com/open-policy-agent/conftest/tree/master/examples) for policy layout and structured-input testing.
- [OPA policy testing](https://www.openpolicyagent.org/docs/latest/policy-testing/) for Rego unit-test conventions.
- [Azure built-in policies](https://github.com/Azure/azure-policy/tree/master/built-in-policies) for Azure control intent. These are Azure Policy JSON, not Rego; use them as semantic references, not copy-paste rules.