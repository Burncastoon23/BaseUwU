package com.agentregistry.android.model

data class AgentSku(
    val skuCode: String,
    val agentId: String,
    val category: String,
    val subcategory: String,
    val tier: String,
    val provider: String,
    val avgSuccessRate: Double,
    val capabilityCount: Int,
    val active: Boolean,
    val supersededBysku: String?,
    val tags: List<String>,
    val listedAt: String,
    val lastUpdated: String,
)

data class AgentCapability(
    val name: String,
    val description: String,
    val inputTypes: List<String>,
    val outputTypes: List<String>,
    val verified: Boolean,
    val successRate: Double,
)

data class AgentCard(
    val agentId: String,
    val name: String,
    val version: String,
    val description: String,
    val provider: String,
    val endpoint: String,
    val trustLevel: String,
    val skills: List<AgentCapability>,
    val verificationDate: String?,
    val ttlSeconds: Int,
)

data class HealthStatus(
    val status: String,
    val agentCount: Int,
    val staleCount: Int,
)
