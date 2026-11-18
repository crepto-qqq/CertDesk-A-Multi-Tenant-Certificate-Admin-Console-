const actors = [
  { email: 'alice@east.test', tenant: 'East', zone: 'Australia/Sydney' },
  { email: 'bob@west.test', tenant: 'West', zone: 'Australia/Perth' }
]

async function api(actor, url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { 'X-Actor': actor, ...options.headers }
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.error || `Request failed (HTTP ${response.status}).`)
  }
  return response
}

Vue.createApp({
  data() {
    return {
      actors, actor: actors[0].email,
      sortFields: [
        { value: 'date', label: 'Issue date' }, { value: 'learner', label: 'Learner' },
        { value: 'course', label: 'Course' }, { value: 'serial', label: 'Serial number' },
        { value: 'status', label: 'Status' }
      ],
      search: '', appliedSearch: '', sort: 'date', direction: 'desc', page: 1, pageSize: 20,
      loading: true, listError: '', items: [], total: 0, listRequest: 0, searchTimer: null,
      epoch: 0, exporting: false, exportError: '',
      modal: '', courses: [], courseId: null, coursesLoading: false, coursesError: '',
      pendingKeys: {}, bulkBusy: false, bulkError: '', bulkResult: null,
      detail: null, detailId: null, detailRequest: 0, detailLoading: false, detailError: '',
      confirming: false, revoking: false, revokeSuccess: false, revokeError: ''
    }
  },
  computed: {
    currentActor() { return actors.find(person => person.email === this.actor) },
    keySlot() { return this.actor + '/' + this.courseId },
    retryPending() { return Boolean(this.pendingKeys[this.keySlot]) },
    resultSummary() {
      const counts = { issued: 0, skipped: 0, failed: 0 }
      this.bulkResult.outcomes.forEach(row => { counts[row.outcome] += 1 })
      return `${counts.issued} issued · ${counts.skipped} skipped · ${counts.failed} failed`
    }
  },
  watch: {
    search() {
      clearTimeout(this.searchTimer)
      this.searchTimer = setTimeout(() => this.applySearch(), 230)
    }
  },
  mounted() {
    this.loadList()
    this.loadCourses()
  },
  methods: {
    localText(value) { return value ? value.replace('T', ' ').slice(0, 16) : '—' },
    titleCase(value) { return value ? value[0].toUpperCase() + value.slice(1).toLowerCase() : '' },
    reasonText(value) { return String(value).replaceAll('_', ' ') },
    changeActor(email) {
      if (this.actor === email) return
      this.epoch += 1
      this.actor = email
      this.closeDialog()
      clearTimeout(this.searchTimer)
      this.search = ''
      this.appliedSearch = ''
      this.page = 1
      this.items = []
      this.total = 0
      this.courses = []
      this.courseId = null
      this.clearBulkResult()
      this.exporting = false
      this.exportError = ''
      this.loadList()
      this.loadCourses()
    },
    query(q = this.appliedSearch) {
      return new URLSearchParams({ q, sort: this.sort, direction: this.direction })
    },
    applySearch() {
      clearTimeout(this.searchTimer)
      if (this.appliedSearch === this.search.trim()) return
      this.appliedSearch = this.search.trim()
      this.resetPage()
    },
    clearSearch() { this.search = ''; this.applySearch() },
    resetPage() { this.page = 1; this.loadList() },
    toggleDirection() {
      this.direction = this.direction === 'asc' ? 'desc' : 'asc'
      this.resetPage()
    },
    movePage(offset) { this.page += offset; this.loadList() },
    async loadList() {
      const request = ++this.listRequest
      this.loading = true
      this.listError = ''
      const params = this.query()
      params.set('page', this.page)
      params.set('page_size', this.pageSize)
      try {
        const response = await api(this.actor, '/api/certificates?' + params)
        const result = await response.json()
        if (request === this.listRequest) {
          this.items = result.items
          this.total = result.total
        }
      } catch (error) {
        if (request === this.listRequest) this.listError = error.message
      } finally {
        if (request === this.listRequest) this.loading = false
      }
    },
    async exportCsv() {
      if (this.exporting) return
      this.applySearch()
      this.exporting = true
      this.exportError = ''
      const epoch = this.epoch
      try {
        const response = await api(this.actor, '/api/certificates/export.csv?' + this.query())
        const blob = await response.blob()
        if (epoch !== this.epoch) return
        const url = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = this.currentActor.tenant.toLowerCase() + '-certificates.csv'
        document.body.append(link)
        link.click()
        link.remove()
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      } catch (error) {
        if (epoch === this.epoch) this.exportError = 'CSV export failed. ' + error.message
      } finally {
        if (epoch === this.epoch) this.exporting = false
      }
    },
    async loadCourses() {
      const epoch = this.epoch
      this.coursesLoading = true
      this.coursesError = ''
      try {
        const response = await api(this.actor, '/api/courses')
        const result = await response.json()
        if (epoch === this.epoch) {
          this.courses = result.items
          this.courseId = result.items[0]?.id ?? null
        }
      } catch (error) {
        if (epoch === this.epoch) this.coursesError = error.message
      } finally {
        if (epoch === this.epoch) this.coursesLoading = false
      }
    },
    showDialog(name) {
      this.modal = name
      this.$nextTick(() => {
        if (this.modal === name && !this.$refs.dialog.open) this.$refs.dialog.showModal()
      })
    },
    closeDialog() {
      if (this.$refs.dialog.open) this.$refs.dialog.close()
      this.onDialogClose()
    },
    handleCancel(event) {
      if (this.bulkBusy || this.revoking) event.preventDefault()
    },
    onDialogClose() {
      if (this.$refs.dialog.open) return
      this.modal = ''
      this.detailRequest += 1
      this.detail = null
      this.confirming = false
    },
    openBulk() { this.showDialog('bulk') },
    clearBulkResult() { this.bulkError = ''; this.bulkResult = null },
    async issue() {
      if (this.bulkBusy || !this.courseId) return
      const slot = this.keySlot
      const epoch = this.epoch
      this.clearBulkResult()
      this.bulkBusy = true
      try {
        const key = this.pendingKeys[slot] || crypto.randomUUID()
        this.pendingKeys[slot] = key
        const response = await api(this.actor, '/api/bulk-issue', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
          body: JSON.stringify({ course_id: this.courseId })
        })
        const result = await response.json()
        delete this.pendingKeys[slot]
        if (epoch === this.epoch) {
          this.bulkResult = result
          this.loadList()
        }
      } catch (error) {
        if (epoch === this.epoch) this.bulkError = 'Issuance could not be confirmed. ' + error.message
      } finally {
        if (epoch === this.epoch) this.bulkBusy = false
      }
    },
    async openDetail(id) {
      this.detailId = id
      this.detail = null
      this.confirming = false
      this.revokeError = ''
      this.revokeSuccess = false
      this.showDialog('detail')
      await this.loadDetail()
    },
    async loadDetail() {
      const request = ++this.detailRequest
      this.detailError = ''
      this.detailLoading = true
      try {
        const response = await api(this.actor, '/api/certificates/' + this.detailId)
        const result = await response.json()
        if (request === this.detailRequest) this.detail = result
      } catch (error) {
        if (request === this.detailRequest) this.detailError = error.message
      } finally {
        if (request === this.detailRequest) this.detailLoading = false
      }
    },
    async revoke() {
      if (this.revoking || !this.confirming || this.detail?.status !== 'ACTIVE') return
      const epoch = this.epoch
      this.revoking = true
      this.revokeError = ''
      try {
        await api(this.actor, '/api/certificates/' + this.detail.id + '/revoke', { method: 'POST' })
        if (epoch !== this.epoch) return
        this.confirming = false
        this.revokeSuccess = true
        this.loadList()
        await this.loadDetail()
      } catch (error) {
        if (epoch === this.epoch) this.revokeError = 'Revocation could not be confirmed. ' + error.message
      } finally {
        if (epoch === this.epoch) this.revoking = false
      }
    }
  }
}).mount('#app')
