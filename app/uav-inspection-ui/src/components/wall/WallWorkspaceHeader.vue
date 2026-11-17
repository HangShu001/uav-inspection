<script setup lang="ts">
import { ArrowLeft, Building2, FolderClock, LayoutDashboard } from 'lucide-vue-next'

defineProps<{ active: 'workbench' | 'archive' }>()
</script>

<template>
  <header class="wall-header">
    <div class="wall-header-inner">
      <RouterLink to="/" class="wall-brand">
        <span class="wall-brand-icon"><Building2 :size="21" :stroke-width="1.8" /></span>
        <span>建筑外墙巡检</span>
      </RouterLink>
      <nav aria-label="外墙巡检" class="wall-nav">
        <RouterLink to="/assets?category=wall-model">素材与权重</RouterLink>
        <RouterLink to="/wall" :aria-current="active === 'workbench' ? 'page' : undefined">
          <LayoutDashboard :size="17" /> 巡检工作台
        </RouterLink>
        <RouterLink to="/wall/replay" :aria-current="active === 'archive' ? 'page' : undefined">
          <FolderClock :size="17" /> 历史任务
        </RouterLink>
      </nav>
      <RouterLink to="/" class="wall-home"><ArrowLeft :size="16" /> 返回首页</RouterLink>
    </div>
  </header>
</template>
