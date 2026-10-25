# Azure Network Rego Policies

These Conftest policies evaluate ARM JSON produced by `bicep build`. They
currently require a VNet, a non-empty address-prefix list, at least one subnet,
and an `Experiment` tag. They also reject NSG rules that allow public inbound
SSH/RDP or wildcard destination ports.

This is an initial policy set, not complete scenario acceptance. CIDR overlap,
subnet containment, private-endpoint requirements, and scenario-specific
connectivity are not yet covered.

## Validate a Bicep Template

```powershell
bicep build templates/bicep/net-01-basic-vnet.bicep --outfile $env:TEMP/net-01.json
conftest test $env:TEMP/net-01.json --policy policies/azure --output json
```

## Run Rego Unit Tests

OPA tests are kept outside the Conftest policy directory so Conftest loads only
production rules:

```powershell
opa test policies/azure tests/rego -v
```

## Reference Repositories

- [Conftest examples](https://github.com/open-policy-agent/conftest/tree/master/examples) for policy layout and structured-input testing.
- [OPA policy testing](https://www.openpolicyagent.org/docs/latest/policy-testing/) for Rego unit-test conventions.
- [Azure built-in policies](https://github.com/Azure/azure-policy/tree/master/built-in-policies) for Azure control intent. These are Azure Policy JSON, not Rego; use them as semantic references, not copy-paste rules.