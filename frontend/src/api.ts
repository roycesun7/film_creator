const BASE = ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `API error ${res.status}`)
  }
  return res.json()
}

// Stats
export const fetchStats = () => request<Stats>('/api/stats')

// Media
export const fetchMedia = (params: { limit?: number; offset?: number; sort?: string; media_type?: string }) => {
  const q = new URLSearchParams()
  if (params.limit) q.set('limit', String(params.limit))
  if (params.offset) q.set('offset', String(params.offset))
  if (params.sort) q.set('sort', params.sort)
  if (params.media_type) q.set('media_type', params.media_type)
  return request<MediaListResponse>(`/api/media?${q}`)
}

export const fetchMediaDetail = (uuid: string) =>
  request<MediaItem>(`/api/media/${uuid}`)

export const deleteMediaItem = (uuid: string) =>
  request<{ deleted: boolean }>(`/api/media/${uuid}`, { method: 'DELETE' })

// Search
export const searchMedia = (body: SearchRequest) =>
  request<SearchResponse>('/api/search', { method: 'POST', body: JSON.stringify(body) })

// Index
export const startIndex = (body: IndexRequest) =>
  request<{ job_id: string }>('/api/index', { method: 'POST', body: JSON.stringify(body) })

// Preview
export const previewVideo = (body: PreviewRequest) =>
  request<EDLResponse>('/api/preview', { method: 'POST', body: JSON.stringify(body) })

// Generate
export const startGenerate = (body: GenerateRequest) =>
  request<{ job_id: string }>('/api/generate', { method: 'POST', body: JSON.stringify(body) })

// Jobs
export const fetchJob = (jobId: string) => request<Job>(`/api/jobs/${jobId}`)
export const fetchJobs = () => request<{ jobs: Job[] }>('/api/jobs')

// Videos
export const fetchVideos = () => request<{ videos: VideoFile[] }>('/api/videos')

export const deleteVideo = (filename: string) =>
  request<{ deleted: boolean; filename: string }>(`/api/videos/${encodeURIComponent(filename)}`, { method: 'DELETE' })

export const videoThumbnailUrl = (filename: string) =>
  `/api/videos/${encodeURIComponent(filename)}/thumbnail`

// Music upload
export async function uploadMusic(file: File): Promise<MusicUploadResponse> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch('/api/upload-music', { method: 'POST', body: formData })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Music upload failed: ${res.status}`)
  }
  return res.json()
}

// Custom generate (user-reordered EDL)
export const startCustomGenerate = (body: CustomGenerateRequest) =>
  request<{ job_id: string }>('/api/generate-custom', { method: 'POST', body: JSON.stringify(body) })

// Upload
export async function uploadFiles(files: FileList | File[], describe = false): Promise<UploadResponse> {
  const formData = new FormData()
  for (const file of Array.from(files)) {
    formData.append('files', file)
  }
  const url = describe ? '/api/upload?describe=true' : '/api/upload'
  const res = await fetch(url, { method: 'POST', body: formData })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Upload failed: ${res.status}`)
  }
  return res.json()
}

export interface UploadResponse {
  uploaded: number
  results: { filename: string; uuid?: string; media_type?: string; status?: string; error?: string }[]
}

// Thumbnail URL helper
export const thumbnailUrl = (uuid: string) => `/api/media/${uuid}/thumbnail`

// Video playback URL helper
export const videoUrl = (uuid: string) => `/api/media/${uuid}/video`

// Types
export interface Stats {
  total: number
  photos: number
  videos: number
  with_embeddings: number
  with_descriptions: number
  date_range: { earliest: string; latest: string } | null
  top_albums: { name: string; count: number }[]
  top_persons: { name: string; count: number }[]
  avg_quality: number | null
}

export interface MediaItem {
  uuid: string
  path: string
  media_type: string
  date: string | null
  lat: number | null
  lon: number | null
  albums: string[]
  labels: string[]
  persons: string[]
  width: number | null
  height: number | null
  duration: number | null
  description: Record<string, any>
  quality_score: number | null
}

export interface MediaListResponse {
  items: MediaItem[]
  total: number
  limit: number
  offset: number
}

export interface SearchRequest {
  query: string
  albums?: string[]
  persons?: string[]
  min_quality?: number
  limit?: number
  fast?: boolean
}

export interface SearchResponse {
  results: (MediaItem & { relevance_score?: number })[]
  count: number
  query: string
}

export interface IndexRequest {
  limit?: number
  album?: string
  after?: string
  before?: string
  describe?: boolean
  force?: boolean
}

export interface PreviewRequest {
  prompt: string
  duration?: number
  albums?: string[]
  persons?: string[]
  min_quality?: number
  num_candidates?: number
  uuids?: string[]
}

export interface GenerateRequest {
  prompt: string
  duration?: number
  theme?: string
  music?: string
  albums?: string[]
  persons?: string[]
  min_quality?: number
  num_candidates?: number
  uuids?: string[]
}

export interface EDLResponse {
  title: string
  narrative_summary: string
  music_mood: string
  estimated_duration: number
  shots: Shot[]
}

export interface Shot {
  uuid: string
  path: string
  media_type: string
  start_time: number
  end_time: number
  duration: number
  role: string
  reason: string
}

export interface Job {
  id: string
  type: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  progress: number
  message: string
  created_at: number
  updated_at: number
  output_path?: string
  title?: string
}

export interface VideoFile {
  filename: string
  path: string
  size_mb: number
  created_at: string
}

export interface MusicUploadResponse {
  path: string
  filename: string
}

export interface CustomShotInput {
  uuid: string
  start_time: number
  end_time: number
  role: string
  reason: string
}

export interface CustomGenerateRequest {
  shots: CustomShotInput[]
  title: string
  theme: string
  music_path?: string
}
