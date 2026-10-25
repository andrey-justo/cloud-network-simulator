// NET-01: Basic Virtual Network
// Objetivo: Criação de rede virtual básica com validação de CIDR e subnets
// 
// Requisitos de aceitação (B0 - Baseline Manual):
// 1. Resource Group deve existir
// 2. VNet com address space válido (não sobreposto)
// 3. Pelo menos 1 subnet definida
// 4. CIDR da subnet dentro do CIDR do VNet
// 5. Nenhum endereço reservado ou sobreposto

param location string = resourceGroup().location
param vnetName string = 'vnet-basic'
param addressPrefix string = '10.0.0.0/16'
param subnetName string = 'subnet-default'
param subnetPrefix string = '10.0.1.0/24'
param environment string = 'dev'

@description('Tags para identifiação de experimento')
param experimentTags object = {
  scenario: 'NET-01'
  baseline: 'B0'
  createdBy: 'terraform-ai'
  timestamp: utcNow('u')
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-05-01' = {
  name: vnetName
  location: location
  tags: union({
    environment: environment
  }, experimentTags)
  properties: {
    addressSpace: {
      addressPrefixes: [
        addressPrefix
      ]
    }
    subnets: [
      {
        name: subnetName
        properties: {
          addressPrefix: subnetPrefix
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

@export()
output vnetId string = vnet.id
@export()
output vnetName string = vnet.name
@export()
output subnets array = vnet.properties.subnets
@export()
output addressSpace object = vnet.properties.addressSpace
