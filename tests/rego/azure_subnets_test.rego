package azure_network_test

import data.main
import rego.v1

test_inline_subnet if {
    main.has_declared_subnet({"properties": {"subnets": [{"name": "web"}]}})
}

test_literal_child_subnet if {
    main.has_declared_subnet({"name": "vnet"}) with input as {
        "resources": [{"type": "Microsoft.Network/virtualNetworks/subnets", "name": "vnet/web"}],
    }
}

test_unrelated_literal_child_does_not_satisfy_parent if {
    not main.has_declared_subnet({"name": "vnet"}) with input as {
        "resources": [{"type": "Microsoft.Network/virtualNetworks/subnets", "name": "other/web"}],
    }
}

test_expression_child_association_is_deferred if {
    main.has_declared_subnet({"name": "vnet"}) with input as {
        "resources": [{"type": "Microsoft.Network/virtualNetworks/subnets", "name": "[format('{0}/{1}', 'vnet', 'web')]"}],
    }
}

test_missing_subnet_is_denied if {
    not main.has_declared_subnet({"name": "vnet"}) with input as {"resources": []}
}
