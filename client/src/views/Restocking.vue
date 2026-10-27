<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <div class="budget-row">
          <label for="budget-slider" class="budget-label">{{ t('restocking.budget') }}</label>
          <span class="budget-value">{{ formatMoney(budget) }}</span>
        </div>
        <input
          id="budget-slider"
          v-model.number="budget"
          type="range"
          min="0"
          :max="maxBudget"
          :step="BUDGET_STEP"
          class="budget-slider"
        />
        <div class="budget-scale">
          <span>{{ formatMoney(0) }}</span>
          <span>{{ formatMoney(maxBudget) }}</span>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.summary.totalCost') }}</div>
          <div class="stat-value">{{ formatMoney(totalCost) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.summary.remainingBudget') }}</div>
          <div class="stat-value">{{ formatMoney(remainingBudget) }}</div>
        </div>
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.summary.leadTime') }}</div>
          <div class="stat-value">{{ t('restocking.days', { days: orderLeadTime }) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.summary.itemCount') }}</div>
          <div class="stat-value">{{ recommendations.length }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendedItems') }}</h3>
        </div>

        <div v-if="recommendations.length === 0" class="empty-state">{{ t('restocking.empty') }}</div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th>{{ t('restocking.table.quantity') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.lineTotal') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="rec in recommendations" :key="rec.item_sku">
                <td><strong>{{ rec.item_sku }}</strong></td>
                <td>{{ translateProductName(rec.item_name) }}</td>
                <td>
                  <span :class="['badge', rec.trend]">{{ t(`trends.${rec.trend}`) }}</span>
                </td>
                <td>{{ rec.needed }}</td>
                <td>{{ formatMoney(rec.unit_cost) }}</td>
                <td><strong>{{ formatMoney(rec.lineTotal) }}</strong></td>
                <td>{{ rec.lead_time_days }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="order-actions">
        <button
          class="place-order-btn"
          :disabled="recommendations.length === 0 || submitting"
          @click="placeOrder"
        >
          {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
        </button>
        <div v-if="submitError" class="inline-error">{{ submitError }}</div>
        <div v-if="placedOrder" class="inline-success">
          {{ t('restocking.success', { orderNumber: placedOrder.order_number }) }}
          <router-link to="/orders">{{ t('restocking.viewOrders') }}</router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency } from '../utils/currency'

const BUDGET_STEP = 500
const TREND_RANK = { increasing: 0, stable: 1, decreasing: 2 }

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, translateProductName } = useI18n()
    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])
    const budget = ref(0)
    const submitting = ref(false)
    const submitError = ref(null)
    const placedOrder = ref(null)

    const formatMoney = (value) => formatCurrency(value, currentCurrency.value)

    // Items that need restocking, before any budget constraint
    const needed = computed(() => {
      return forecasts.value
        .map(f => {
          const qty = Math.max(0, f.forecasted_demand - f.quantity_on_hand)
          return { ...f, needed: qty, lineTotal: qty * f.unit_cost }
        })
        .filter(f => f.needed > 0)
    })

    // Slider max: cost of restocking everything, rounded up to the step
    const maxBudget = computed(() => {
      const total = needed.value.reduce((sum, f) => sum + f.lineTotal, 0)
      return Math.ceil(total / BUDGET_STEP) * BUDGET_STEP
    })

    const recommendations = computed(() => {
      // Rank by trend (increasing demand first), then by largest shortfall
      const ranked = [...needed.value].sort((a, b) => {
        const rankDiff = (TREND_RANK[a.trend] ?? 3) - (TREND_RANK[b.trend] ?? 3)
        return rankDiff !== 0 ? rankDiff : b.needed - a.needed
      })

      // Greedy pass: take an item at its full needed quantity if it fits the
      // remaining budget; otherwise skip it so smaller items can still fit
      let remaining = budget.value
      const picked = []
      for (const item of ranked) {
        if (item.lineTotal <= remaining) {
          picked.push(item)
          remaining -= item.lineTotal
        }
      }
      return picked
    })

    const totalCost = computed(() => recommendations.value.reduce((sum, r) => sum + r.lineTotal, 0))
    const remainingBudget = computed(() => budget.value - totalCost.value)
    const orderLeadTime = computed(() => {
      return recommendations.value.reduce((max, r) => Math.max(max, r.lead_time_days), 0)
    })

    const loadForecasts = async () => {
      try {
        loading.value = true
        error.value = null
        forecasts.value = await api.getDemandForecasts()
        // Start at 50% of max, rounded to the step
        budget.value = Math.round(maxBudget.value / 2 / BUDGET_STEP) * BUDGET_STEP
      } catch (err) {
        error.value = 'Failed to load demand forecasts: ' + err.message
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (recommendations.value.length === 0 || submitting.value) return
      submitting.value = true
      submitError.value = null
      placedOrder.value = null
      try {
        placedOrder.value = await api.createRestockingOrder(
          recommendations.value.map(r => ({ sku: r.item_sku, quantity: r.needed }))
        )
      } catch (err) {
        submitError.value = err.response?.data?.detail || t('restocking.error')
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadForecasts)

    return {
      t,
      BUDGET_STEP,
      loading,
      error,
      budget,
      maxBudget,
      recommendations,
      totalCost,
      remainingBudget,
      orderLeadTime,
      submitting,
      submitError,
      placedOrder,
      formatMoney,
      placeOrder,
      translateProductName
    }
  }
}
</script>

<style scoped>
.budget-card {
  padding: 1.5rem;
  margin-bottom: 1.5rem;
}

.budget-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 0.75rem;
}

.budget-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.budget-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

.budget-slider {
  width: 100%;
  accent-color: #3b82f6;
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  font-size: 0.813rem;
  color: #64748b;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
}

.order-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 1rem;
  margin-top: 1.5rem;
}

.place-order-btn {
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 0.625rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
}

.place-order-btn:hover:not(:disabled) {
  background: #1e293b;
}

.place-order-btn:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}

.inline-error {
  color: #dc2626;
  font-size: 0.875rem;
}

.inline-success {
  color: #059669;
  font-size: 0.875rem;
}

.inline-success a {
  margin-left: 0.5rem;
  color: #2563eb;
  font-weight: 500;
}
</style>
