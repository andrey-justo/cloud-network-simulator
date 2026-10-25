// NET-03: Secure Network with NSGs
// Objetivo: Regras de segurança entre segmentos com NSG
//
// Requisitos de aceitação:
// 1. NSGs para cada tier (web, app, data)
// 2. Web: permite inbound 80, 443 da Internet
// 3. App: permite inbound apenas de Web
// 4. Data: permite inbound apenas de App
// 5. Egress: restritivo (deny all, allowlist)
// 6. Sem regras excessivamente permissivas (0.0.0.0/0)

param location string = resourceGroup().location
param vnetId string
param environment string = 'dev'

param experimentTags object = {
  scenario: 'NET-03'
  baseline: 'B0'
  createdBy: 'terraform-ai'
  timestamp: utcNow('u')
}

// NSG for Web Tier
resource nsgWeb 'Microsoft.Network/networkSecurityGroups@2023-05-01' = {
  name: 'nsg-web'
  location: location
  tags: union({
    tier: 'web'
    environment: environment
  }, experimentTags)
  properties: {
    securityRules: [
      {
        name: 'AllowHTTP'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '80'
          sourceAddressPrefix: 'Internet'
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 100
          direction: 'Inbound'
        }
      }
      {
        name: 'AllowHTTPS'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: 'Internet'
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 110
          direction: 'Inbound'
        }
      }
      {
        name: 'DenyAllInbound'
        properties: {
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: '*'
          access: 'Deny'
          priority: 4096
          direction: 'Inbound'
        }
      }
    ]
  }
}

// NSG for Application Tier
resource nsgApp 'Microsoft.Network/networkSecurityGroups@2023-05-01' = {
  name: 'nsg-app'
  location: location
  tags: union({
    tier: 'application'
    environment: environment
  }, experimentTags)
  properties: {
    securityRules: [
      {
        name: 'AllowFromWeb'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '8080'
          sourceAddressPrefix: '10.1.1.0/24'  // Web subnet
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 100
          direction: 'Inbound'
        }
      }
      {
        name: 'DenyAllInbound'
        properties: {
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: '*'
          access: 'Deny'
          priority: 4096
          direction: 'Inbound'
        }
      }
    ]
  }
}

// NSG for Data Tier
resource nsgData 'Microsoft.Network/networkSecurityGroups@2023-05-01' = {
  name: 'nsg-data'
  location: location
  tags: union({
    tier: 'data'
    environment: environment
  }, experimentTags)
  properties: {
    securityRules: [
      {
        name: 'AllowFromApp'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '5432'  // PostgreSQL
          sourceAddressPrefix: '10.1.2.0/24'  // App subnet
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 100
          direction: 'Inbound'
        }
      }
      {
        name: 'DenyAllInbound'
        properties: {
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: '*'
          access: 'Deny'
          priority: 4096
          direction: 'Inbound'
        }
      }
    ]
  }
}

@export()
output nsgWebId string = nsgWeb.id
@export()
output nsgAppId string = nsgApp.id
@export()
output nsgDataId string = nsgData.id
