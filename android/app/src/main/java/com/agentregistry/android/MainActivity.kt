package com.agentregistry.android

import android.content.Intent
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import android.widget.EditText
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.SearchView
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.Lifecycle
import androidx.recyclerview.widget.LinearLayoutManager
import com.agentregistry.android.adapter.SkuAdapter
import com.agentregistry.android.databinding.ActivityMainBinding
import com.agentregistry.android.viewmodel.RegistryViewModel
import com.google.android.material.chip.Chip
import com.google.android.material.snackbar.Snackbar
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    private lateinit var viewModel: RegistryViewModel
    private lateinit var adapter: SkuAdapter

    private val categories = listOf("ALL", "CODE", "SEARCH", "DATA", "FINANCE")
    private val tiers = listOf("ALL", "VRF", "DCL", "UNK")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setSupportActionBar(binding.toolbar)

        viewModel = ViewModelProvider(this)[RegistryViewModel::class.java]

        // Restore server config saved from the Settings dialog
        val prefs = getSharedPreferences("agent_registry", MODE_PRIVATE)
        val savedUrl = prefs.getString("server_url", null)
        val savedKey = prefs.getString("api_key", "") ?: ""
        if (savedUrl != null) viewModel.setServerConfig(savedUrl, savedKey)

        adapter = SkuAdapter { sku ->
            val intent = Intent(this, AgentDetailActivity::class.java)
            intent.putExtra("SKU_CODE", sku.skuCode)
            startActivity(intent)
        }

        binding.recyclerView.layoutManager = LinearLayoutManager(this)
        binding.recyclerView.adapter = adapter

        // Category chips
        categories.forEach { category ->
            val chip = Chip(this)
            chip.text = category
            chip.isCheckable = true
            chip.isChecked = category == "ALL"
            chip.setOnClickListener { applyFilters() }
            binding.chipGroupCategory.addView(chip)
        }

        // Tier chips
        tiers.forEach { tier ->
            val chip = Chip(this)
            chip.text = tier
            chip.isCheckable = true
            chip.isChecked = tier == "ALL"
            chip.setOnClickListener { applyFilters() }
            binding.chipGroupTier.addView(chip)
        }

        binding.swipeRefresh.setOnRefreshListener {
            viewModel.loadSkus()
        }

        binding.fab.setOnClickListener {
            viewModel.consolidate(dryRun = false)
        }

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { state ->
                    adapter.submitList(state.skus)
                    binding.swipeRefresh.isRefreshing = state.isLoading
                    state.error?.let { error ->
                        Snackbar.make(binding.root, error, Snackbar.LENGTH_LONG).show()
                    }
                }
            }
        }
    }

    private fun getSelectedCategory(): String {
        for (i in 0 until binding.chipGroupCategory.childCount) {
            val chip = binding.chipGroupCategory.getChildAt(i) as? Chip
            if (chip?.isChecked == true && chip.text != "ALL") return chip.text.toString()
        }
        return ""
    }

    private fun getSelectedTier(): String {
        for (i in 0 until binding.chipGroupTier.childCount) {
            val chip = binding.chipGroupTier.getChildAt(i) as? Chip
            if (chip?.isChecked == true && chip.text != "ALL") return chip.text.toString()
        }
        return ""
    }

    private fun applyFilters() {
        val query = viewModel.state.value.searchQuery
        viewModel.search(query, getSelectedCategory(), getSelectedTier())
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.main_menu, menu)
        val searchItem = menu.findItem(R.id.action_search)
        val searchView = searchItem.actionView as SearchView
        searchView.setOnQueryTextListener(object : SearchView.OnQueryTextListener {
            override fun onQueryTextSubmit(query: String): Boolean {
                viewModel.search(query, getSelectedCategory(), getSelectedTier())
                return true
            }
            override fun onQueryTextChange(newText: String): Boolean {
                if (newText.isEmpty()) viewModel.loadSkus()
                return true
            }
        })
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        return when (item.itemId) {
            R.id.action_settings -> {
                showServerUrlDialog()
                true
            }
            R.id.action_refresh -> {
                viewModel.refresh()
                true
            }
            else -> super.onOptionsItemSelected(item)
        }
    }

    private fun showServerUrlDialog() {
        val container = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL
            setPadding(48, 16, 48, 0)
        }
        val urlInput = EditText(this).apply {
            hint = "Server URL"
            setText(viewModel.state.value.serverUrl)
        }
        val keyInput = EditText(this).apply {
            hint = "API key (optional)"
            setText(viewModel.state.value.apiKey)
        }
        container.addView(urlInput)
        container.addView(keyInput)
        AlertDialog.Builder(this)
            .setTitle("Server settings")
            .setView(container)
            .setPositiveButton("OK") { _, _ ->
                val url = urlInput.text.toString().trimEnd('/')
                val key = keyInput.text.toString().trim()
                if (url.isNotBlank()) {
                    getSharedPreferences("agent_registry", MODE_PRIVATE).edit()
                        .putString("server_url", url)
                        .putString("api_key", key)
                        .apply()
                    viewModel.setServerConfig(url, key)
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }
}
