<template>
  <div class="space-y-6 pb-8">
    <!-- 活跃度热图 + 请求间隔时间线 -->
    <div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
      <ActivityHeatmapCard
        :data="activityHeatmapData"
        :title="isAdminPage ? '总体活跃天数' : '我的活跃天数'"
      />
      <IntervalTimelineCard
        :title="isAdminPage ? '请求间隔时间线' : '我的请求间隔'"
        :is-admin="isAdminPage"
        :hours="24"
      />
    </div>

    <!-- 分析统计 -->
    <!-- 管理员：模型 + 提供商 + API格式（3列） -->
    <div
      v-if="isAdminPage"
      class="grid grid-cols-1 lg:grid-cols-3 gap-4"
    >
      <UsageModelTable
        :data="enhancedModelStats"
        :is-admin="authStore.isAdmin"
      />
      <UsageProviderTable
        :data="providerStats"
        :is-admin="authStore.isAdmin"
      />
      <UsageApiFormatTable
        :data="apiFormatStats"
        :is-admin="authStore.isAdmin"
      />
    </div>
    <!-- 用户：模型 + API格式（2列） -->
    <div
      v-else
      class="grid grid-cols-1 lg:grid-cols-2 gap-4"
    >
      <UsageModelTable
        :data="enhancedModelStats"
        :is-admin="authStore.isAdmin"
      />
      <UsageApiFormatTable
        :data="apiFormatStats"
        :is-admin="false"
      />
    </div>

    <!-- 请求详情 -->
    <UsageRecordsTable
      :records="displayRecords"
      :is-admin="isAdminPage"
      :show-actual-cost="authStore.isAdmin"
      :loading="isLoadingRecords"
      :selected-period="selectedPeriod"
      :filter-user="filterUser"
      :filter-model="filterModel"
      :filter-provider="filterProvider"
      :filter-status="filterStatus"
      :available-users="availableUsers"
      :available-models="availableModels"
      :available-providers="availableProviders"
      :current-page="currentPage"
      :page-size="pageSize"
      :total-records="totalRecords"
      :page-size-options="pageSizeOptions"
      @update:selected-period="handlePeriodChange"
      @update:filter-user="handleFilterUserChange"
      @update:filter-model="handleFilterModelChange"
      @update:filter-provider="handleFilterProviderChange"
      @update:filter-status="handleFilterStatusChange"
      @update:current-page="handlePageChange"
      @update:page-size="handlePageSizeChange"
      @refresh="refreshData"
      @export="exportData"
      @show-detail="showRequestDetail"
    />

    <!-- 请求详情抽屉 - 仅管理员可见 -->
    <RequestDetailDrawer
      v-if="isAdminPage"
      :is-open="detailModalOpen"
      :request-id="selectedRequestId"
      @close="detailModalOpen = false"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { usageApi } from '@/api/usage'
import { usersApi } from '@/api/users'
import { meApi } from '@/api/me'
import {
  UsageModelTable,
  UsageProviderTable,
  UsageApiFormatTable,
  UsageRecordsTable,
  ActivityHeatmapCard,
  RequestDetailDrawer,
  IntervalTimelineCard
} from '@/features/usage/components'
import {
  useUsageData,
  getDateRangeFromPeriod
} from '@/features/usage/composables'
import type { PeriodValue, FilterStatusValue } from '@/features/usage/types'
import type { UserOption } from '@/features/usage/components/UsageRecordsTable.vue'
import { log } from '@/utils/logger'

const route = useRoute()
const authStore = useAuthStore()

// 判断是否是管理员页面
const isAdminPage = computed(() => route.path.startsWith('/admin'))

// 时间段选择
const selectedPeriod = ref<PeriodValue>('today')

// 分页状态
const currentPage = ref(1)
const pageSize = ref(20)
const pageSizeOptions = [10, 20, 50, 100]

// 筛选状态
const filterUser = ref('__all__')
const filterModel = ref('__all__')
const filterProvider = ref('__all__')
const filterStatus = ref<FilterStatusValue>('__all__')

// 用户列表（仅管理员页面使用）
const availableUsers = ref<UserOption[]>([])

// 使用 composables
const {
  isLoadingRecords,
  providerStats,
  apiFormatStats,
  currentRecords,
  totalRecords,
  enhancedModelStats,
  activityHeatmapData,
  availableModels,
  availableProviders,
  loadStats,
  loadRecords
} = useUsageData({ isAdminPage })

// 用户页面需要前端筛选
const filteredRecords = computed(() => {
  if (!isAdminPage.value) {
    let records = [...currentRecords.value]

    if (filterModel.value !== '__all__') {
      records = records.filter(record => record.model === filterModel.value)
    }

    if (filterProvider.value !== '__all__') {
      records = records.filter(record => record.provider === filterProvider.value)
    }

    if (filterStatus.value !== '__all__') {
      if (filterStatus.value === 'stream') {
        records = records.filter(record =>
          record.is_stream && !record.error_message && (!record.status_code || record.status_code === 200)
        )
      } else if (filterStatus.value === 'standard') {
        records = records.filter(record =>
          !record.is_stream && !record.error_message && (!record.status_code || record.status_code === 200)
        )
      } else if (filterStatus.value === 'error') {
        records = records.filter(record =>
          record.error_message || (record.status_code && record.status_code >= 400)
        )
      } else if (filterStatus.value === 'active') {
        records = records.filter(record =>
          record.status === 'pending' || record.status === 'streaming'
        )
      } else if (filterStatus.value === 'pending') {
        records = records.filter(record => record.status === 'pending')
      } else if (filterStatus.value === 'streaming') {
        records = records.filter(record => record.status === 'streaming')
      } else if (filterStatus.value === 'completed') {
        records = records.filter(record => record.status === 'completed')
      } else if (filterStatus.value === 'failed') {
        // 失败请求需要同时考虑新旧两种判断方式：
        // 1. 新方式：status = "failed"
        // 2. 旧方式：status_code >= 400 或 error_message 不为空
        records = records.filter(record =>
          record.status === 'failed' ||
          (record.status_code && record.status_code >= 400) ||
          record.error_message
        )
      }
    }

    return records
  }
  return currentRecords.value
})

// 获取活跃请求的 ID 列表
const activeRequestIds = computed(() => {
  return currentRecords.value
    .filter(record => record.status === 'pending' || record.status === 'streaming')
    .map(record => record.id)
})

// 检查是否有活跃请求
const hasActiveRequests = computed(() => activeRequestIds.value.length > 0)

// 自动刷新定时器
let autoRefreshTimer: ReturnType<typeof setInterval> | null = null
const AUTO_REFRESH_INTERVAL = 1000 // 1秒刷新一次

// 轮询活跃请求状态（轻量级，只更新状态变化的记录）
async function pollActiveRequests() {
  if (!hasActiveRequests.value) return

  try {
    // 根据页面类型选择不同的 API
    const idsParam = activeRequestIds.value.join(',')
    const { requests } = isAdminPage.value
      ? await usageApi.getActiveRequests(activeRequestIds.value)
      : await meApi.getActiveRequests(idsParam)

    // 检查是否有状态变化
    let hasChanges = false
    for (const update of requests) {
      const record = currentRecords.value.find(r => r.id === update.id)
      if (record && record.status !== update.status) {
        hasChanges = true
        // 如果状态变为 completed 或 failed，需要刷新获取完整数据
        if (update.status === 'completed' || update.status === 'failed') {
          break
        }
        // 否则只更新状态和 token 信息
        record.status = update.status
        record.input_tokens = update.input_tokens
        record.output_tokens = update.output_tokens
        record.cost = update.cost
        record.response_time_ms = update.response_time_ms ?? undefined
      }
    }

    // 如果有请求完成或失败，刷新整个列表获取完整数据
    if (hasChanges && requests.some(r => r.status === 'completed' || r.status === 'failed')) {
      await refreshData()
    }
  } catch (error) {
    log.error('轮询活跃请求状态失败:', error)
  }
}

// 启动自动刷新
function startAutoRefresh() {
  if (autoRefreshTimer) return
  autoRefreshTimer = setInterval(pollActiveRequests, AUTO_REFRESH_INTERVAL)
}

// 停止自动刷新
function stopAutoRefresh() {
  if (autoRefreshTimer) {
    clearInterval(autoRefreshTimer)
    autoRefreshTimer = null
  }
}

// 监听活跃请求状态，自动启动/停止刷新
watch(hasActiveRequests, (hasActive) => {
  if (hasActive) {
    startAutoRefresh()
  } else {
    stopAutoRefresh()
  }
}, { immediate: true })

// 组件卸载时清理定时器
onUnmounted(() => {
  stopAutoRefresh()
})

// 用户页面的前端分页
const paginatedRecords = computed(() => {
  if (!isAdminPage.value) {
    const start = (currentPage.value - 1) * pageSize.value
    const end = start + pageSize.value
    return filteredRecords.value.slice(start, end)
  }
  return currentRecords.value
})

// 显示的记录
const displayRecords = computed(() => paginatedRecords.value)


// 详情弹窗状态
const detailModalOpen = ref(false)
const selectedRequestId = ref<string | null>(null)

// 初始化加载
onMounted(async () => {
  const dateRange = getDateRangeFromPeriod(selectedPeriod.value)
  await loadStats(dateRange)

  // 管理员页面加载用户列表和第一页记录
  if (isAdminPage.value) {
    // 并行加载用户列表和记录
    const [users] = await Promise.all([
      usersApi.getAllUsers(),
      loadRecords({ page: currentPage.value, pageSize: pageSize.value }, getCurrentFilters())
    ])
    availableUsers.value = users.map(u => ({ id: u.id, username: u.username, email: u.email }))
  }
})

// 处理时间段变化
async function handlePeriodChange(value: string) {
  selectedPeriod.value = value as PeriodValue
  currentPage.value = 1  // 重置到第一页

  const dateRange = getDateRangeFromPeriod(selectedPeriod.value)
  await loadStats(dateRange)

  if (isAdminPage.value) {
    await loadRecords({ page: 1, pageSize: pageSize.value }, getCurrentFilters())
  }
}

// 处理分页变化
async function handlePageChange(page: number) {
  currentPage.value = page

  if (isAdminPage.value) {
    await loadRecords({ page, pageSize: pageSize.value }, getCurrentFilters())
  }
}

// 处理每页大小变化
async function handlePageSizeChange(size: number) {
  pageSize.value = size
  currentPage.value = 1  // 重置到第一页

  if (isAdminPage.value) {
    await loadRecords({ page: 1, pageSize: size }, getCurrentFilters())
  }
}

// 获取当前筛选参数
function getCurrentFilters() {
  return {
    user_id: filterUser.value !== '__all__' ? filterUser.value : undefined,
    model: filterModel.value !== '__all__' ? filterModel.value : undefined,
    provider: filterProvider.value !== '__all__' ? filterProvider.value : undefined,
    status: filterStatus.value !== '__all__' ? filterStatus.value : undefined
  }
}

// 处理筛选变化
async function handleFilterUserChange(value: string) {
  filterUser.value = value
  currentPage.value = 1  // 重置到第一页

  if (isAdminPage.value) {
    await loadRecords({ page: 1, pageSize: pageSize.value }, getCurrentFilters())
  }
}

async function handleFilterModelChange(value: string) {
  filterModel.value = value
  currentPage.value = 1  // 重置到第一页

  if (isAdminPage.value) {
    await loadRecords({ page: 1, pageSize: pageSize.value }, getCurrentFilters())
  }
}

async function handleFilterProviderChange(value: string) {
  filterProvider.value = value
  currentPage.value = 1

  if (isAdminPage.value) {
    await loadRecords({ page: 1, pageSize: pageSize.value }, getCurrentFilters())
  }
}

async function handleFilterStatusChange(value: string) {
  filterStatus.value = value as FilterStatusValue
  currentPage.value = 1

  if (isAdminPage.value) {
    await loadRecords({ page: 1, pageSize: pageSize.value }, getCurrentFilters())
  }
}

// 刷新数据
async function refreshData() {
  const dateRange = getDateRangeFromPeriod(selectedPeriod.value)
  await loadStats(dateRange)

  if (isAdminPage.value) {
    await loadRecords({ page: currentPage.value, pageSize: pageSize.value }, getCurrentFilters())
  }
}

// 显示请求详情
function showRequestDetail(id: string) {
  if (!isAdminPage.value) return
  selectedRequestId.value = id
  detailModalOpen.value = true
}

// 导出数据
async function exportData(format: 'csv' | 'json') {
  try {
    const blob = await usageApi.exportUsage(format)
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `usage-stats.${format}`
    a.click()
    window.URL.revokeObjectURL(url)
  } catch (error) {
    log.error('导出失败:', error)
  }
}
</script>

<style scoped>
</style>
