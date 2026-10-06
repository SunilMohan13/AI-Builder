import type { PopulationRiskArea, IndustrySite, Notification } from '../types'

/**
 * Ranked exposure areas along the transport corridor.
 *
 * Ordered by exposure, which is severity times people — not by
 * concentration. That is why Delhi North outranks Karnal even though Karnal
 * sits closer to the fires: the plume thins as it travels and the population
 * it reaches grows by an order of magnitude.
 */
export const mockRiskAreas: PopulationRiskArea[] = [
  { rank: 1, name: 'Delhi North', risk: 'SEVERE', population: 890000, lat: 28.72, lon: 77.15 },
  { rank: 2, name: 'Delhi East (Shahdara)', risk: 'SEVERE', population: 760000, lat: 28.68, lon: 77.29 },
  { rank: 3, name: 'Ghaziabad', risk: 'HIGH', population: 620000, lat: 28.67, lon: 77.45 },
  { rank: 4, name: 'Noida / Gautam Buddha Nagar', risk: 'HIGH', population: 540000, lat: 28.54, lon: 77.39 },
  { rank: 5, name: 'Sonipat', risk: 'HIGH', population: 380000, lat: 28.99, lon: 77.02 },
  { rank: 6, name: 'Panipat', risk: 'MEDIUM', population: 310000, lat: 29.39, lon: 76.97 },
  { rank: 7, name: 'Gurugram', risk: 'MEDIUM', population: 295000, lat: 28.46, lon: 77.03 },
  { rank: 8, name: 'Karnal', risk: 'LOW', population: 200000, lat: 29.69, lon: 76.99 },
]

export const mockIndustries: IndustrySite[] = [
  { id: 'ind_1', name: 'Panipat Refinery', lat: 29.42, lon: 76.95, type: 'Refinery' },
  { id: 'ind_2', name: 'Bhiwadi Industrial', lat: 28.21, lon: 76.86, type: 'Manufacturing' },
  { id: 'ind_3', name: 'Ludhiana Textile', lat: 30.9, lon: 75.85, type: 'Textile' },
  { id: 'ind_4', name: 'Bahadurgarh brick kiln cluster', lat: 28.69, lon: 76.93, type: 'Brick kiln' },
  { id: 'ind_5', name: 'Faridabad industrial belt', lat: 28.39, lon: 77.31, type: 'Manufacturing' },
  { id: 'ind_6', name: 'Rajpura thermal', lat: 30.48, lon: 76.59, type: 'Thermal power' },
]

export const mockNotifications: Notification[] = [
  {
    id: 'n1',
    title: 'High pollution event detected',
    message: 'Punjab agricultural burning — EVT-1024',
    time: '2 min ago',
    route: '/events/EVT-1024',
    icon: 'fire',
  },
  {
    id: 'n2',
    title: 'Forecast risk increased',
    message: 'Delhi NCR exposure projected to rise within 6h',
    time: '8 min ago',
    route: '/forecast',
    icon: 'forecast',
  },
  {
    id: 'n3',
    title: 'Sentinel-5P delayed',
    message: 'Satellite data delayed by 2h. Predictions continue.',
    time: '2 hr ago',
    route: '/sources',
    icon: 'warning',
  },
  {
    id: 'n4',
    title: 'Citizen report corroborated',
    message: 'Smoke photo near Sangrur matches 6 FIRMS detections within 12 km',
    time: '12 min ago',
    route: '/citizen',
    icon: 'fire',
  },
  {
    id: 'n5',
    title: 'Hazard model withheld',
    message: 'pm25_hazard_24h failed its promotion gate — serving the labelled baseline',
    time: '1 hr ago',
    route: '/sources',
    icon: 'warning',
  },
]
