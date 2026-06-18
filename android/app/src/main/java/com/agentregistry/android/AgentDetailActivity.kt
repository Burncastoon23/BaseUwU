package com.agentregistry.android

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.agentregistry.android.adapter.CapabilityAdapter
import com.agentregistry.android.databinding.ActivityAgentDetailBinding
import com.agentregistry.android.network.ApiClient
import com.google.android.material.snackbar.Snackbar
import kotlinx.coroutines.launch

class AgentDetailActivity : AppCompatActivity() {
    private lateinit var binding: ActivityAgentDetailBinding
    private lateinit var apiClient: ApiClient

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityAgentDetailBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setSupportActionBar(binding.toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        supportActionBar?.title = "Agent Detail"

        val skuCode = intent.getStringExtra("SKU_CODE") ?: run {
            finish()
            return
        }

        // Try to get stored server URL from shared preferences or use default
        val prefs = getSharedPreferences("agent_registry", MODE_PRIVATE)
        val serverUrl = prefs.getString("server_url", "http://10.0.2.2:8080") ?: "http://10.0.2.2:8080"
        apiClient = ApiClient(serverUrl)

        binding.recyclerViewCapabilities.layoutManager = LinearLayoutManager(this)

        lifecycleScope.launch {
            binding.progressBar.visibility = android.view.View.VISIBLE
            val result = apiClient.getAgentCard(skuCode)
            binding.progressBar.visibility = android.view.View.GONE

            result.fold(
                onSuccess = { card ->
                    supportActionBar?.title = card.name
                    binding.tvAgentName.text = card.name
                    binding.tvVersion.text = "v${card.version}"
                    binding.tvProvider.text = card.provider
                    binding.tvEndpoint.text = card.endpoint
                    binding.tvDescription.text = card.description

                    val trustColor = when (card.trustLevel) {
                        "verified" -> 0xFF4CAF50.toInt()
                        "self_declared" -> 0xFF2196F3.toInt()
                        else -> 0xFF9E9E9E.toInt()
                    }
                    binding.tvTrustBadge.text = card.trustLevel
                    binding.tvTrustBadge.setTextColor(trustColor)
                    binding.tvTrustBadge.setBackgroundColor(trustColor and 0x00FFFFFF or 0x1A000000)

                    card.verificationDate?.let {
                        binding.tvVerificationDate.text = "Verified: $it"
                        binding.tvVerificationDate.visibility = android.view.View.VISIBLE
                    }

                    binding.recyclerViewCapabilities.adapter = CapabilityAdapter(card.skills)
                },
                onFailure = { e ->
                    Snackbar.make(binding.root, e.message ?: "Failed to load agent", Snackbar.LENGTH_LONG).show()
                }
            )
        }
    }

    override fun onSupportNavigateUp(): Boolean {
        onBackPressedDispatcher.onBackPressed()
        return true
    }
}
