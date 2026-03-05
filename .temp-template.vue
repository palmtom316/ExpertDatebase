<template>
  <div class="app-layout" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <!-- Collapsible Left Sidebar -->
    <aside class="sidebar" :aria-expanded="!sidebarCollapsed">
      <div class="sidebar-header">
        <div class="brand">
          <svg class="brand-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 002-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
          </svg>
          <h1 class="brand-title" v-if="!sidebarCollapsed">BidExpert</h1>
        </div>
        <button class="btn btn-ghost toggle-btn" @click="sidebarCollapsed = !sidebarCollapsed" aria-label="Toggle Sidebar">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
            <path v-if="sidebarCollapsed" stroke-linecap="round" stroke-linejoin="round" d="M13 5l7 7-7 7M5 5l7 7-7 7" />
            <path v-else stroke-linecap="round" stroke-linejoin="round" d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
          </svg>
        </button>
      </div>

      <nav class="sidebar-nav">
        <!-- Navigation actions grouped -->
        <div class="nav-group">
          <label class="nav-label" v-if="!sidebarCollapsed">分类设置</label>
          <div class="nav-field" :class="{'is-collapsed': sidebarCollapsed}">
             <select v-model="selectedUploadDocType" class="nav-select">
              <option v-for="item in docTypeOptions" :key="item" :value="item">{{ item }}</option>
            </select>
            <span class="nav-icon-only" v-if="sidebarCollapsed" title="文档分类">📁</span>
          </div>
        </div>
        
        <div class="nav-actions">
           <button class="nav-btn btn-primary" type="button" :disabled="isUploading" @click="triggerUpload">
             <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="nav-icon"><path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/></svg>
             <span v-if="!sidebarCollapsed">上传 PDF</span>
           </button>
           <button class="nav-btn btn-secondary" type="button" @click="startEvalRun">
             <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="nav-icon"><path stroke-linecap="round" stroke-linejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/><path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
             <span v-if="!sidebarCollapsed">启动评测</span>
           </button>
           <button class="nav-btn btn-ghost" type="button" @click="settingsDrawerOpen = true">
             <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="nav-icon"><path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
             <span v-if="!sidebarCollapsed">API 设置</span>
           </button>
           <button class="nav-btn btn-primary copilot-trigger" type="button" @click="toggleCopilot">
             <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="nav-icon"><path stroke-linecap="round" stroke-linejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/></svg>
             <span v-if="!sidebarCollapsed">Copilot (⌘J)</span>
           </button>
        </div>
      </nav>
    </aside>

    <input ref="pdfInputRef" class="hidden-input" type="file" accept=".pdf,application/pdf" @change="onFileChange" />

    <!-- Main Console -->
    <main class="main-console" @click="collapseCopilotIfNarrow">
      <div class="console-header">
        <h2 class="page-title">Workspace 控制台</h2>
      </div>
      
      <div class="console-grid">
        <UploadPanel
          :upload-message="uploadMessage"
          :upload-message-mode="uploadMessageMode"
          :upload-meta="uploadMeta"
          @retry-failed="retryFailed"
        />
        <DocList
          :docs="docsState"
          :selected-doc-id="selectedDocId"
          :deleting-version-id="deletingVersionId"
          :doc-type-options="docTypeOptions"
          @select-doc="selectDocRow"
          @load-artifacts="loadArtifacts"
          @add-to-eval="addToEvalDataset"
          @reprocess="reprocessDoc"
          @delete-doc="deleteDoc"
          @doc-type-filter-change="onDocTypeFilterChange"
        />
        <QualityPanel :quality="quality" />
      </div>
    </main>

    <CopilotDrawer
      :collapsed="copilotCollapsed"
      :messages="chatMessages"
      :sending="chatSending"
      :evidence="reviewEvidence"
      :evidence-title="reviewTitle"
      :evidence-quality="evidenceQuality"
      @close="collapseCopilot"
      @clear-history="clearCopilotHistory"
      @send-chat="sendChat"
    />

    <SettingsDrawer
      :open="settingsDrawerOpen"
      :model-value="settings"
      :conn-state="connState"
      @close="settingsDrawerOpen = false"
      @update:model-value="applySettings"
      @save="saveSettings"
      @test-conn="onTestConn"
    />
  </div>
</template>