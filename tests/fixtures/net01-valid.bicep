targetScope = 'resourceGroup'

param studySuffix string = 'local'

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: 'benchmark-vnet'
  location: resourceGroup().location
  tags: {
    Experiment: 'validator-smoke'
  }
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.1.0.0/16'
      ]
    }
    subnets: [
      {
        name: 'web'
        properties: {
          addressPrefix: '10.1.1.0/24'
        }
      }
    ]
  }
}
