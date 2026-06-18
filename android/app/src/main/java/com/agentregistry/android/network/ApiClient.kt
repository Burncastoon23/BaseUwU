package com.agentregistry.android.network

import com.agentregistry.android.model.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject

class ApiClient(var baseUrl: String = "http://10.0.2.2:8080") {

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, java.util.concurrent.TimeUnit.SECONDS)
        .readTimeout(15, java.util.concurrent.TimeUnit.SECONDS)
        .build()
    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()

    suspend fun listSkus(): Result<List<AgentSku>> = withContext(Dispatchers.IO) {
        runCatching {
            val body = get("/sku")
            JSONArray(body).let { arr ->
                (0 until arr.length()).map { arr.getJSONObject(it).toAgentSku() }
            }
        }
    }

    suspend fun searchSkus(query: String = "", category: String = "", tier: String = ""): Result<List<AgentSku>> = withContext(Dispatchers.IO) {
        runCatching {
            val params = buildString {
                if (query.isNotBlank()) append("q=${java.net.URLEncoder.encode(query, "UTF-8")}&")
                if (category.isNotBlank()) append("category=$category&")
                if (tier.isNotBlank()) append("tier=$tier")
            }.trimEnd('&')
            val path = if (params.isBlank()) "/sku/search" else "/sku/search?$params"
            val body = get(path)
            JSONArray(body).let { arr ->
                (0 until arr.length()).map { arr.getJSONObject(it).toAgentSku() }
            }
        }
    }

    suspend fun getSkuDetail(skuCode: String): Result<AgentSku> = withContext(Dispatchers.IO) {
        runCatching {
            JSONObject(get("/sku/$skuCode")).toAgentSku()
        }
    }

    suspend fun getAgentCard(skuCode: String): Result<AgentCard> = withContext(Dispatchers.IO) {
        runCatching {
            JSONObject(get("/sku/$skuCode/agent")).toAgentCard()
        }
    }

    suspend fun health(): Result<HealthStatus> = withContext(Dispatchers.IO) {
        runCatching {
            val obj = JSONObject(get("/health"))
            HealthStatus(
                status = obj.getString("status"),
                agentCount = obj.getInt("agent_count"),
                staleCount = obj.getInt("stale_count"),
            )
        }
    }

    suspend fun runConsolidation(dryRun: Boolean = false): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            post("/agents/consolidate?dry_run=$dryRun")
        }
    }

    suspend fun triggerRefresh(): Result<String> = withContext(Dispatchers.IO) {
        runCatching { post("/agents/refresh") }
    }

    suspend fun getCatalog(): Result<String> = withContext(Dispatchers.IO) {
        runCatching { get("/sku/catalog") }
    }

    private fun get(path: String): String {
        val request = Request.Builder().url("$baseUrl$path").get().build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw Exception("HTTP ${response.code}: ${response.message}")
            return response.body?.string() ?: throw Exception("Empty response body")
        }
    }

    private fun post(path: String, body: String = "{}"): String {
        val requestBody = body.toRequestBody(jsonMediaType)
        val request = Request.Builder().url("$baseUrl$path").post(requestBody).build()
        client.newCall(request).execute().use { response ->
            return response.body?.string() ?: ""
        }
    }

    private fun JSONObject.toAgentSku(): AgentSku {
        val tagsArr = optJSONArray("tags") ?: org.json.JSONArray()
        return AgentSku(
            skuCode = getString("sku_code"),
            agentId = getString("agent_id"),
            category = optString("category", "GEN"),
            subcategory = optString("subcategory", ""),
            tier = optString("tier", "UNK"),
            provider = optString("provider", ""),
            avgSuccessRate = optDouble("avg_success_rate", 0.0),
            capabilityCount = optInt("capability_count", 0),
            active = optBoolean("active", true),
            supersededBysku = if (isNull("superseded_by_sku")) null else optString("superseded_by_sku"),
            tags = (0 until tagsArr.length()).map { tagsArr.getString(it) },
            listedAt = optString("listed_at", ""),
            lastUpdated = optString("last_updated", ""),
        )
    }

    private fun JSONObject.toAgentCard(): AgentCard {
        val skillsArr = optJSONArray("skills") ?: JSONArray()
        return AgentCard(
            agentId = getString("agent_id"),
            name = getString("name"),
            version = optString("version", ""),
            description = optString("description", ""),
            provider = optString("provider", ""),
            endpoint = optString("endpoint", ""),
            trustLevel = optString("trust_level", "unverified"),
            skills = (0 until skillsArr.length()).map { skillsArr.getJSONObject(it).toCapability() },
            verificationDate = if (isNull("verification_date")) null else optString("verification_date"),
            ttlSeconds = optInt("ttl_seconds", 86400),
        )
    }

    private fun JSONObject.toCapability(): AgentCapability {
        val inArr = optJSONArray("input_types") ?: JSONArray()
        val outArr = optJSONArray("output_types") ?: JSONArray()
        return AgentCapability(
            name = optString("name", ""),
            description = optString("description", ""),
            inputTypes = (0 until inArr.length()).map { inArr.getString(it) },
            outputTypes = (0 until outArr.length()).map { outArr.getString(it) },
            verified = optBoolean("verified", false),
            successRate = optDouble("success_rate", 0.0),
        )
    }
}
