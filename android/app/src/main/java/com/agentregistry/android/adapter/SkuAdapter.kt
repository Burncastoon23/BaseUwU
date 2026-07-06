package com.agentregistry.android.adapter

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.agentregistry.android.R
import com.agentregistry.android.databinding.ItemSkuBinding
import com.agentregistry.android.model.AgentSku

class SkuAdapter(private val onItemClick: (AgentSku) -> Unit) :
    ListAdapter<AgentSku, SkuAdapter.ViewHolder>(DiffCallback) {

    inner class ViewHolder(val binding: ItemSkuBinding) : RecyclerView.ViewHolder(binding.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val binding = ItemSkuBinding.inflate(LayoutInflater.from(parent.context), parent, false)
        return ViewHolder(binding)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val sku = getItem(position)
        val b = holder.binding
        val ctx = b.root.context

        b.tvSkuCode.text = sku.skuCode
        b.tvProvider.text = sku.provider.ifBlank { "—" }
        b.tvCategory.text = "${sku.category} · ${sku.capabilityCount} capabilities"
        val pct = (sku.avgSuccessRate * 100).toInt().coerceIn(0, 100)
        b.tvSuccessRate.text = "$pct%"

        val (tierLabel, tierColorRes) = when (sku.tier) {
            "VRF" -> "Verified" to R.color.color_tier_vrf
            "DCL" -> "Declared" to R.color.color_tier_dcl
            else  -> "Unknown"  to R.color.color_tier_unk
        }
        b.tvTier.text = tierLabel
        b.tvTier.setTextColor(ContextCompat.getColor(ctx, tierColorRes))

        b.tvActive.text = if (sku.active) "ACTIVE" else "INACTIVE"
        b.tvActive.setTextColor(
            ContextCompat.getColor(ctx, if (sku.active) R.color.color_active else R.color.color_inactive)
        )

        b.root.setOnClickListener { onItemClick(sku) }
    }

    companion object DiffCallback : DiffUtil.ItemCallback<AgentSku>() {
        override fun areItemsTheSame(a: AgentSku, b: AgentSku) = a.skuCode == b.skuCode
        override fun areContentsTheSame(a: AgentSku, b: AgentSku) = a == b
    }
}
