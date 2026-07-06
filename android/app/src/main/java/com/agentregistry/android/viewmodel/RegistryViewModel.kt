package com.agentregistry.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.agentregistry.android.model.AgentSku
import com.agentregistry.android.network.ApiClient
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch

data class RegistryUiState(
    val skus: List<AgentSku> = emptyList(),
    val isLoading: Boolean = false,
    val error: String? = null,
    val serverUrl: String = com.agentregistry.android.BuildConfig.DEFAULT_BASE_URL,
    val apiKey: String = "",
    val agentCount: Int = 0,
    val staleCount: Int = 0,
    val searchQuery: String = "",
)

class RegistryViewModel : ViewModel() {
    private val _state = MutableStateFlow(RegistryUiState())
    val state: StateFlow<RegistryUiState> = _state.asStateFlow()

    var apiClient = ApiClient(_state.value.serverUrl)
        private set

    fun loadSkus() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            apiClient.listSkus()
                .onSuccess { skus -> _state.update { it.copy(skus = skus, isLoading = false) } }
                .onFailure { e -> _state.update { it.copy(error = e.message, isLoading = false) } }
            apiClient.health()
                .onSuccess { h -> _state.update { it.copy(agentCount = h.agentCount, staleCount = h.staleCount) } }
        }
    }

    fun search(query: String, category: String = "", tier: String = "") {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            apiClient.searchSkus(query, category, tier)
                .onSuccess { skus -> _state.update { it.copy(skus = skus, isLoading = false) } }
                .onFailure { e -> _state.update { it.copy(error = e.message, isLoading = false) } }
        }
    }

    fun setServerConfig(url: String, apiKey: String = _state.value.apiKey) {
        apiClient = ApiClient(url, apiKey)
        _state.update { it.copy(serverUrl = url, apiKey = apiKey) }
        loadSkus()
    }

    fun consolidate(dryRun: Boolean = false) {
        viewModelScope.launch {
            apiClient.runConsolidation(dryRun)
                .onSuccess { loadSkus() }
                .onFailure { e -> _state.update { it.copy(error = e.message) } }
        }
    }

    fun refresh() {
        viewModelScope.launch {
            apiClient.triggerRefresh()
                .onSuccess { loadSkus() }
                .onFailure { e -> _state.update { it.copy(error = e.message) } }
        }
    }
}
