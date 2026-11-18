import { use } from 'echarts/core'
import { BarChart, PieChart } from 'echarts/charts'
import { LegendComponent } from 'echarts/components'

use([BarChart, PieChart, LegendComponent])

export { init } from './index'
