package main

import rego.v1

resources := object.get(input, "resources", [])

has_vnet if {
    some resource in resources
    lower(object.get(resource, "type", "")) == "microsoft.network/virtualnetworks"
}

deny contains msg if {
    not has_vnet
    msg := "Template must declare at least one Microsoft.Network/virtualNetworks resource."
}

deny contains msg if {
    some resource in resources
    lower(object.get(resource, "type", "")) == "microsoft.network/virtualnetworks"
    properties := object.get(resource, "properties", {})
    address_space := object.get(properties, "addressSpace", {})
    prefixes := object.get(address_space, "addressPrefixes", [])
    count(prefixes) == 0
    msg := sprintf("VNet %q must declare at least one address prefix.", [object.get(resource, "name", "<unnamed>")])
}

deny contains msg if {
    some resource in resources
    lower(object.get(resource, "type", "")) == "microsoft.network/virtualnetworks"
    properties := object.get(resource, "properties", {})
    subnets := object.get(properties, "subnets", [])
    count(subnets) == 0
    msg := sprintf("VNet %q must declare at least one subnet.", [object.get(resource, "name", "<unnamed>")])
}

deny contains msg if {
    some resource in resources
    lower(object.get(resource, "type", "")) == "microsoft.network/virtualnetworks"
    tags := object.get(resource, "tags", {})
    not object.get(tags, "Experiment", false)
    msg := sprintf("VNet %q must include the Experiment tag.", [object.get(resource, "name", "<unnamed>")])
}

deny contains msg if {
    some resource in resources
    lower(object.get(resource, "type", "")) == "microsoft.network/networksecuritygroups"
    properties := object.get(resource, "properties", {})
    rules := object.get(properties, "securityRules", [])
    some rule in rules
    rule_properties := object.get(rule, "properties", {})
    lower(object.get(rule_properties, "access", "")) == "allow"
    lower(object.get(rule_properties, "direction", "")) == "inbound"
    sources := array.concat(
        [object.get(rule_properties, "sourceAddressPrefix", "")],
        object.get(rule_properties, "sourceAddressPrefixes", [])
    )
    ports := array.concat(
        [object.get(rule_properties, "destinationPortRange", "")],
        object.get(rule_properties, "destinationPortRanges", [])
    )
    some source in sources
    is_public_prefix(source)
    some port in ports
    is_management_port(port)
    msg := sprintf("NSG %q rule %q allows public inbound SSH/RDP traffic.", [object.get(resource, "name", "<unnamed>"), object.get(rule, "name", "<unnamed>")])
}

is_public_prefix(prefix) if {
    is_string(prefix)
    lower(prefix) in {"*", "internet", "0.0.0.0/0", "any"}
}

is_management_port(port) if { port == "22" }
is_management_port(port) if { port == "3389" }
is_management_port(port) if { port == "*" }