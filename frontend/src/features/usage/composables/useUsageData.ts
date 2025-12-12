import { ref, computed, type Ref } from 'vue'
import { usageApi } from '@/api/usage'
import { meApi } from '@/api/me'
import type {
  UsageStatsState,
  ModelStatsItem,
  ProviderStatsItem,
  ApiFormatStatsItem,
  UsageRecord,
  DateRangeParams,
  EnhancedModelStatsItem
} from '../types'
import { createDefaultStats } from '../types'
import { log } from '@/utils/logger'

export interface UseUsageDataOptions {
  isAdminPage: Ref<boolean>
}

export interface PaginationParams {
  page: number
  pageSize: number
}

export interface FilterParams {
  user_id?: string
  model?: string
  provider?: string
  status?: string
}

export function useUsageData(options: UseUsageDataOptions) {
  const { isAdminPage } = options

  // 加载状态
  const isLoadingStats = ref(true)
  const isLoadingRecords = ref(false)
  const loading = computed(() => isLoadingStats.value || isLoadingRecords.value)

  // 统计数据
  const stats = ref<UsageStatsState>(createDefaultStats())
  const modelStats = ref<ModelStatsItem[]>([])
  const providerStats = ref<ProviderStatsItem[]>([])
  const apiFormatStats = ref<ApiFormatStatsItem[]>([])

  // 记录数据 - 只存储当前页
  const currentRecords = ref<UsageRecord[]>([])
  const totalRecords = ref(0)

  // 当前的日期范围（用于分页请求）
  const currentDateRange = ref<DateRangeParams | undefined>(undefined)

  // 可用的筛选选项（从统计数据获取，而不是从记录中）
  const availableModels = ref<string[]>([])
  const availableProviders = ref<string[]>([])

  // 增强的模型统计（包含效率分析）
  const enhancedModelStats = computed<EnhancedModelStatsItem[]>(() => {
    return modelStats.value.map(model => ({
      ...model,
      costPerToken: model.total_tokens > 0
        ? `$${(model.total_cost / model.total_tokens * 1000000).toFixed(2)}/M`
        : '-'
    }))
  })

  // 活跃度热图数据
  const activityHeatmapData = computed(() => stats.value.activity_heatmap)

  // 加载统计数据（不加载记录）
  async function loadStats(dateRange?: DateRangeParams) {
    isLoadingStats.value = true
    currentDateRange.value = dateRange

    try {
      if (isAdminPage.value) {
        // 管理员页面，并行加载统计数据
        const [statsData, modelData, providerData, apiFormatData] = await Promise.all([
          usageApi.getUsageStats(dateRange),
          usageApi.getUsageByModel(dateRange),
          usageApi.getUsageByProvider(dateRange),
          usageApi.getUsageByApiFormat(dateRange)
        ])

        stats.value = {
          total_requests: statsData.total_requests || 0,
          total_tokens: statsData.total_tokens || 0,
          total_cost: statsData.total_cost || 0,
          total_actual_cost: (statsData as any).total_actual_cost,
          avg_response_time: statsData.avg_response_time || 0,
          error_count: (statsData as any).error_count,
          error_rate: (statsData as any).error_rate,
          cache_stats: (statsData as any).cache_stats,
          period_start: '',
          period_end: '',
          activity_heatmap: statsData.activity_heatmap || null
        }

        modelStats.value = modelData.map(item => ({
          model: item.model,
          request_count: item.request_count || 0,
          total_tokens: item.total_tokens || 0,
          total_cost: item.total_cost || 0,
          actual_cost: (item as any).actual_cost
        }))

        providerStats.value = providerData.map(item => ({
          provider: item.provider,
          requests: item.request_count,
          totalTokens: item.total_tokens || 0,
          totalCost: item.total_cost,
          actualCost: item.actual_cost,
          successRate: item.success_rate,
          avgResponseTime: item.avg_response_time_ms > 0
            ? `${(item.avg_response_time_ms / 1000).toFixed(2)}s`
            : '-'
        }))

        apiFormatStats.value = apiFormatData.map(item => ({
          api_format: item.api_format,
          request_count: item.request_count || 0,
          total_tokens: item.total_tokens || 0,
          total_cost: item.total_cost || 0,
          actual_cost: item.actual_cost,
          avgResponseTime: item.avg_response_time_ms > 0
            ? `${(item.avg_response_time_ms / 1000).toFixed(2)}s`
            : '-'
        }))

        // 从统计数据中提取可用的筛选选项
        availableModels.value = modelData.map(item => item.model).filter(Boolean).sort()
        availableProviders.value = providerData.map(item => item.provider).filter(Boolean).sort()

      } else {
        // 用户页面
        const userData = await meApi.getUsage(dateRange)

        stats.value = {
          total_requests: userData.total_requests || 0,
          total_tokens: userData.total_tokens || 0,
          total_cost: userData.total_cost || 0,
          total_actual_cost: userData.total_actual_cost,
          avg_response_time: userData.avg_response_time || 0,
          period_start: '',
          period_end: '',
          activity_heatmap: userData.activity_heatmap || null
        }

        modelStats.value = (userData.summary_by_model || []).map((item: any) => ({
          model: item.model,
          request_count: item.requests || 0,
          total_tokens: item.total_tokens || 0,
          total_cost: item.total_cost_usd || 0,
          actual_cost: item.actual_total_cost_usd
        }))

        providerStats.value = (userData.summary_by_provider || []).map((item: any) => ({
          provider: item.provider,
          requests: item.requests || 0,
          totalCost: item.total_cost_usd || 0,
          successRate: item.success_rate || 0,
          avgResponseTime: item.avg_response_time_ms > 0
            ? `${(item.avg_response_time_ms / 1000).toFixed(2)}s`
            : '-'
        }))

        // 用户页面：记录直接从 userData 获取（数量较少）
        currentRecords.value = (userData.records || []) as UsageRecord[]
        totalRecords.value = currentRecords.value.length

        // 从记录中提取筛选选项和 API 格式统计
        const models = new Set<string>()
        const providers = new Set<string>()
        const apiFormatMap = new Map<string, {
          count: number
          tokens: number
          cost: number
          totalResponseTime: number
          responseTimeCount: number
        }>()

        currentRecords.value.forEach(record => {
          if (record.model) models.add(record.model)
          if (record.provider) providers.add(record.provider)
          if (record.api_format) {
            const existing = apiFormatMap.get(record.api_format) || {
              count: 0,
              tokens: 0,
              cost: 0,
              totalResponseTime: 0,
              responseTimeCount: 0
            }
            existing.count++
            existing.tokens += record.total_tokens || 0
            existing.cost += record.cost || 0
            if (record.response_time_ms) {
              existing.totalResponseTime += record.response_time_ms
              existing.responseTimeCount++
            }
            apiFormatMap.set(record.api_format, existing)
          }
        })

        availableModels.value = Array.from(models).sort()
        availableProviders.value = Array.from(providers).sort()

        // 构建 API 格式统计数据
        apiFormatStats.value = Array.from(apiFormatMap.entries())
          .map(([format, data]) => {
            const avgMs = data.responseTimeCount > 0
              ? data.totalResponseTime / data.responseTimeCount
              : 0
            return {
              api_format: format,
              request_count: data.count,
              total_tokens: data.tokens,
              total_cost: data.cost,
              avgResponseTime: avgMs > 0 ? `${(avgMs / 1000).toFixed(2)}s` : '-'
            }
          })
          .sort((a, b) => b.request_count - a.request_count)
      }
    } catch (error: any) {
      if (error.response?.status !== 403) {
        log.error('加载统计数据失败:', error)
      }
      stats.value = createDefaultStats()
      modelStats.value = []
      currentRecords.value = []
    } finally {
      isLoadingStats.value = false
    }
  }

  // 加载记录（真正的后端分页）
  async function loadRecords(
    pagination: PaginationParams,
    filters?: FilterParams
  ): Promise<void> {
    if (!isAdminPage.value) {
      // 用户页面不需要分页加载，记录已在 loadStats 中获取
      return
    }

    isLoadingRecords.value = true

    try {
      const offset = (pagination.page - 1) * pagination.pageSize

      // 构建请求参数
      const params: any = {
        limit: pagination.pageSize,
        offset,
        ...currentDateRange.value
      }

      // 添加筛选条件
      if (filters?.user_id) {
        params.user_id = filters.user_id
      }
      if (filters?.model) {
        params.model = filters.model
      }
      if (filters?.provider) {
        params.provider = filters.provider
      }
      if (filters?.status) {
        params.status = filters.status
      }

      const response = await usageApi.getAllUsageRecords(params)

      currentRecords.value = (response.records || []) as UsageRecord[]
      totalRecords.value = response.total || 0

    } catch (error) {
      log.error('加载记录失败:', error)
      currentRecords.value = []
      totalRecords.value = 0
    } finally {
      isLoadingRecords.value = false
    }
  }

  // 刷新所有数据
  async function refreshData(dateRange?: DateRangeParams) {
    await loadStats(dateRange)
  }

  return {
    // 状态
    loading,
    isLoadingStats,
    isLoadingRecords,
    stats,
    modelStats,
    providerStats,
    apiFormatStats,
    currentRecords,
    totalRecords,

    // 筛选选项
    availableModels,
    availableProviders,

    // 计算属性
    enhancedModelStats,
    activityHeatmapData,

    // 方法
    loadStats,
    loadRecords,
    refreshData
  }
}
