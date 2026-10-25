package azure_network_test

import data.main
import rego.v1

valid_vnet := {
    "type": "Microsoft.Network/virtualNetworks",
    "name": "vnet-test",
    "tags": {"Experiment": "true"},
    "properties": {
        "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
        "subnets": [{"name": "app", "properties": {"addressPrefix": "10.0.1.0/24"}}],
    },
}

test_accepts_valid_vnet if {
    arm := {"resources": [valid_vnet]}
    violations := main.deny with input as arm
    count(violations) == 0
}

test_requires_vnet if {
    violations := main.deny with input as {"resources": []}
    count(violations) == 1
}

test_rejects_public_ssh if {
    arm := {
        "resources": [valid_vnet, {
            "type": "Microsoft.Network/networkSecurityGroups",
            "name": "nsg-public-ssh",
            "properties": {
                "securityRules": [{
                    "name": "allow-ssh",
                    "properties": {
                        "access": "Allow",
                        "direction": "Inbound",
                        "sourceAddressPrefix": "0.0.0.0/0",
                        "destinationPortRange": "22",
                    },
                }],
            },
        }],
    }
    violations := main.deny with input as arm
    count(violations) == 1
    some violation in violations
    contains(violation, "public inbound SSH/RDP")
}

test_rejects_public_rdp_with_plural_fields if {
    arm := {
        "resources": [valid_vnet, {
            "type": "Microsoft.Network/networkSecurityGroups",
            "name": "nsg-public-rdp",
            "properties": {
                "securityRules": [{
                    "name": "allow-rdp",
                    "properties": {
                        "access": "Allow",
                        "direction": "Inbound",
                        "sourceAddressPrefixes": ["Internet"],
                        "destinationPortRanges": ["3389"],
                    },
                }],
            },
        }],
    }
    violations := main.deny with input as arm
    count(violations) == 1
}

test_allows_private_ssh_source if {
    arm := {
        "resources": [valid_vnet, {
            "type": "Microsoft.Network/networkSecurityGroups",
            "name": "nsg-private-ssh",
            "properties": {
                "securityRules": [{
                    "name": "allow-private-ssh",
                    "properties": {
                        "access": "Allow",
                        "direction": "Inbound",
                        "sourceAddressPrefix": "10.0.0.0/8",
                        "destinationPortRange": "22",
                    },
                }],
            },
        }],
    }
    violations := main.deny with input as arm
    count(violations) == 0
}