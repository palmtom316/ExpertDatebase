<template>
  <section class="card quality-card">
    <h3>抽取质量趋势</h3>
    <div class="quality-metrics">
      <div class="metric-box"><span class="metric-label">综合等级</span><strong class="metric-value">{{ quality.grade }}</strong></div>
      <div class="metric-box"><span class="metric-label">综合分</span><strong class="metric-value">{{ quality.score }}</strong></div>
      <div class="metric-box"><span class="metric-label">样本数</span><strong class="metric-value">{{ quality.count }}</strong></div>
    </div>
    <div class="table-container q-table-wrap">
      <table class="data-table quality-table">
        <thead>
          <tr>
            <th>Sample ID</th>
            <th>Model Provider</th>
            <th>Score</th>
            <th>Time</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in quality.rows" :key="row.id || row.sample_id">
            <td class="mono-text">{{ row.sample_id || "-" }}</td>
            <td>{{ `${row.provider || "-"} / ${row.model || "-"}` }}</td>
            <td><span class="score-badge">{{ Math.round(Number(row.score_total || 0)) }}</span></td>
            <td class="time-text">{{ row.created_at || "-" }}</td>
          </tr>
          <tr v-if="quality.rows.length === 0">
            <td colspan="4" class="empty-state">暂无评测记录</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup>
defineProps({
  quality: {
    type: Object,
    default: () => ({ grade: "-", score: 0, count: 0, rows: [] }),
  },
});
</script>
