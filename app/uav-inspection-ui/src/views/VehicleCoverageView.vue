<script setup lang="ts">
import { webPath } from '../utils/webroot'

const replayUrl = webPath('/vehicle-coverage-demo/index.html#workbench')
</script>

<template>
  <iframe
    :src="replayUrl"
    title="车辆覆盖率检测"
    class="block h-dvh w-full border-0"
  ></iframe>
</template>
