package com.agentregistry.android.adapter

import android.content.res.ColorStateList
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.agentregistry.android.R
import com.agentregistry.android.model.AgentSku
import com.google.android.material.chip.Chip
import com.google.android.material.progressindicator.LinearProgressIndicator

class SkuAdapter(private val onItemClick: (AgentSku) -> Unit) :
    ListAdapter<AgentSku, SkuAdapter.ViewHolder>(DiffCallback) {

    inner class ViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        val skuCode: TextView = itemView.findViewById(R.id.sku_code)
        val tierChip: Chip = itemView.findViewById(R.id.trust_tier_chip)
        val agentName: TextView = itemView.findViewById(R.id.agent_name)
        val provider: TextView = itemView.findViewById(R.id.provider)
        val successBar: LinearProgressIndicator = itemView.findViewById(R.id.success_rate_bar)
        val successText: TextView = itemView.findViewById(R.id.success_rate_text)
        val capCount: TextView = itemView.findViewById(R.id.capability_count)
        val tags: TextView = itemView.findViewById(R.id.tags)
        val statusIcon: View = itemView.findViewById(R.id.status_icon)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_sku, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val sku = getItem(position)
        holder.skuCode.text = sku.skuCode
        holder.agentName.text = sku.agentId.replace("-", " ").replaceFirstChar { it.uppercase() }
        holder.provider.text = sku.provider.ifBlank { "—" }
        val pct = (sku.avgSuccessRate * 100).toInt().coerceIn(0, 100)
        holder.successBar.progress = pct
        holder.successText.text = "$pct%"
        holder.capCount.text = "${sku.capabilityCount} capabilities"
        holder.tags.text = sku.tags.take(4).joinToString(" · ")
        holder.statusIcon.visibility = if (sku.active) View.GONE else View.VISIBLE

        val (tierLabel, tierColorRes) = when (sku.tier) {
            "VRF" -> "Verified" to R.color.color_tier_vrf
            "DCL" -> "Declared" to R.color.color_tier_dcl
            else  -> "Unknown"  to R.color.color_tier_unk
        }
        holder.tierChip.text = tierLabel
        val tierColor = ContextCompat.getColor(holder.itemView.context, tierColorRes)
        holder.tierChip.chipBackgroundColor = ColorStateList.valueOf(tierColor).withAlpha(30)
        holder.tierChip.setTextColor(tierColor)

        holder.itemView.setOnClickListener { onItemClick(sku) }
    }

    companion object DiffCallback : DiffUtil.ItemCallback<AgentSku>() {
        override fun areItemsTheSame(a: AgentSku, b: AgentSku) = a.skuCode == b.skuCode
        override fun areContentsTheSame(a: AgentSku, b: AgentSku) = a == b
    }
}
