<template>
  <section class="card upload-card" aria-live="polite">
    <div class="section-head">
      <h3>上传与任务状态</h3>
      <button class="btn btn-secondary btn-sm" type="button" @click="$emit('retryFailed')">重试失败任务</button>
    </div>
    <div class="status-message" :data-mode="uploadMessageMode">{{ uploadMessage }}</div>
    <div class="meta-grid">
      <div class="meta-item"><span class="meta-label">doc_id</span><span class="meta-value">{{ uploadMeta.docId || "-" }}</span></div>
      <div class="meta-item"><span class="meta-label">version_id</span><span class="meta-value">{{ uploadMeta.versionId || "-" }}</span></div>
      <div class="meta-item"><span class="meta-label">object_key</span><span class="meta-value">{{ uploadMeta.objectKey || "-" }}</span></div>
      <div class="meta-item"><span class="meta-label">状态</span><span class="meta-value">{{ uploadMeta.versionStatus || "-" }}</span></div>
      <div class="meta-item"><span class="meta-label">分类</span><span class="meta-value">{{ uploadMeta.docType || "-" }}</span></div>
    </div>
  </section>
</template>

<script setup>
defineProps({
  uploadMessage: { type: String, default: "" },
  uploadMessageMode: { type: String, default: "info" },
  uploadMeta: { type: Object, required: true },
});
defineEmits(["retryFailed"]);
</script>
