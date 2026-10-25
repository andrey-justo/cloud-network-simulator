// NET-02: Network Segmentation with Subnets (Three Tiers)
// Objetivo: Segmentação por camadas (Web, Application, Data)
//
// Requisitos de aceitação:
// 1. VNet com 3 subnets: web, app, data
// 2. Subnets com CIDR não sobrepostos
// 3. Cada subnet dentro do CIDR do VNet
// 4. Network Policies desabilitadas
// 5. Tags de identidade corretas

param location string = resourceGroup().location
param vnetName string = 'vnet-segmented'
param addressPrefix string = '10.1.0.0/16'
param environment string = 'dev'

@description('Tier de segurança')
param securityTier string = 'prod'

param subnetConfig array = [
  {
    name: 'subnet-web'
    prefix: '10.1.1.0/24'
    tier: 'web'
  }
  {
    name: 'subnet-app'
    prefix: '10.1.2.0/24'
    tier: 'application'
  }
  {
    name: 'subnet-data'
    prefix: '10.1.3.0/24'
    tier: 'data'
  }
]

param experimentTags object = {
  scenario: 'NET-02'
  baseline: 'B0'
  createdBy: 'terraform-ai'
  timestamp: utcNow('u')
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-05-01' = {
  name: vnetName
  location: location
  tags: union({
    environment: environment
    securityTier: securityTier
  }, experimentTags)
  properties: {
    addressSpace: {
      addressPrefixes: [
        addressPrefix
      ]
    }
    subnets: [for subnet in subnetConfig: {
      name: subnet.name
      properties: {
        addressPrefix: subnet.prefix
        privateEndpointNetworkPolicies: 'Disabled'
        privateLinkServiceNetworkPolicies: 'Disabled'
      }
    }]
  }
}

@export()
output vnetId string = vnet.id
@export()
output vnetName string = vnet.name
@export()
output webSubnet object = {
  id: vnet.properties.subnets[0].id
  name: vnet.properties.subnets[0].name
  prefix: vnet.properties.subnets[0].properties.addressPrefix
}
@export()
output appSubnet object = {
  id: vnet.properties.subnets[1].id
  name: vnet.properties.subnets[1].name
  prefix: vnet.properties.subnets[1].properties.addressPrefix
}
@export()
output dataSubnet object = {
  id: vnet.properties.subnets[2].id
  name: vnet.properties.subnets[2].name
  prefix: vnet.properties.subnets[2].properties.addressPrefix
}
