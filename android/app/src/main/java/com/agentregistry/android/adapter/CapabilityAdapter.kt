package com.agentregistry.android.adapter

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.agentregistry.android.R
import com.agentregistry.android.model.AgentCapability
import com.google.android.material.progressindicator.LinearProgressIndicator

class CapabilityAdapter(private val capabilities: List<AgentCapability>) :
    RecyclerView.Adapter<CapabilityAdapter.CapabilityViewHolder>() {

    inner class CapabilityViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        val name: TextView = itemView.findViewById(R.id.tvCapabilityName)
        val description: TextView = itemView.findViewById(R.id.tvCapabilityDescription)
        val successRate: LinearProgressIndicator = itemView.findViewById(R.id.progressSuccessRate)
        val successRateLabel: TextView = itemView.findViewById(R.id.tvSuccessRateLabel)
        val verified: TextView = itemView.findViewById(R.id.tvVerified)
        val inputTypes: TextView = itemView.findViewById(R.id.tvInputTypes)
        val outputTypes: TextView = itemView.findViewById(R.id.tvOutputTypes)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): CapabilityViewHolder {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_capability, parent, false)
        return CapabilityViewHolder(view)
    }

    override fun onBindViewHolder(holder: CapabilityViewHolder, position: Int) {
        val cap = capabilities[position]
        holder.name.text = cap.name
        holder.description.text = cap.description
        val rate = (cap.successRate * 100).toInt().coerceIn(0, 100)
        holder.successRate.progress = rate
        holder.successRateLabel.text = "$rate%"
        holder.verified.text = if (cap.verified) "VERIFIED" else "UNVERIFIED"
        holder.verified.setTextColor(if (cap.verified) 0xFF4CAF50.toInt() else 0xFF9E9E9E.toInt())
        holder.inputTypes.text = "In: ${cap.inputTypes.joinToString(", ")}"
        holder.outputTypes.text = "Out: ${cap.outputTypes.joinToString(", ")}"
    }

    override fun getItemCount() = capabilities.size
}
