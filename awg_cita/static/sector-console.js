(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const wait = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));
  const fixtureReference = Date.now();
  const ago = (milliseconds) => new Date(fixtureReference - milliseconds).toISOString();

  const STATUS_ORDER = ['ONLINE', 'IDLE', 'STALE', 'NEVER', 'DISABLED'];
  const STATUS_RANK = Object.fromEntries(STATUS_ORDER.map((status, index) => [status, index]));
  const PREVIEW_NAME_PATTERN = /^[\p{L}\p{N}][\p{L}\p{N} ._-]{1,47}$/u;
  const PREVIEW_TAG_PATTERN = /^[\p{L}\p{N}][\p{L}\p{N}._-]{0,23}$/u;
  const PREVIEW_ID_PATTERN = /^preview-[A-Za-z0-9_-]{1,64}$/;
  const CONFIG_PREVIEW_ID_PATTERN = /^config-preview-[A-Za-z0-9_-]{1,96}$/;
  const EXPIRATION_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
  const MAX_CLIENT_RECORDS = 64;
  const MAX_NOTES_LENGTH = 240;

  const translations = {
    ru: {
      consoleLabel: 'ОПЕРАТОРСКАЯ КОНСОЛЬ',
      navOverview: 'Обзор',
      navClients: 'Клиенты',
      navJournal: 'Журнал',
      mockBoundary: 'UI READY / BACKEND STUB',
      railBoundary: 'Мутации отключены',
      perimeter: 'ЛОКАЛЬНЫЙ КОНТУР',
      summaryEyebrow: '01 — СВОДКА',
      titleLineOne: 'Узел',
      titleLineTwo: 'управления',
      subtitle: 'Безопасная operator telemetry для AmneziaWG.',
      refresh: 'Обновить',
      refreshInProgress: 'Обновление…',
      addClient: 'Создать preview',
      mutationBoundary: 'Live lifecycle mutations отключены; эта кнопка открывает только preview.',
      overviewEyebrow: '01 / OVERVIEW',
      overviewHeading: 'Состояние узла',
      lastRefresh: 'Последнее обновление',
      state: 'Состояние',
      stateDescription: 'frontend state готов',
      active: 'Активны',
      traffic: 'Трафик сессии',
      trafficDescription: 'RX + TX по fixture dataset',
      attention: 'Внимание',
      attentionDescription: 'stale / never / disabled',
      activityEyebrow: 'EVENT STREAM',
      activityHeading: 'Журнал активности',
      healthEyebrow: 'CONTROL PLANE',
      healthHeading: 'Сигналы состояния',
      totalPeers: 'Всего клиентов',
      onlinePeers: 'Online',
      disabledPeers: 'Отключены',
      stalePeers: 'Stale',
      attentionPeers: 'Требуют внимания',
      adapterMode: 'Adapter',
      adapterMock: 'MOCK LIFECYCLE',
      clientsEyebrow: '02 / REGISTRY',
      journalEyebrow: '03 / OBSERVABILITY',
      journalHeading: 'Наблюдение и аудит',
      journalSubtitle: 'Сводка состояния, безопасные события и evidence export без секретов.',
      exportJson: 'Экспорт JSON',
      exportCsv: 'Экспорт CSV',
      retentionLabel: 'RETENTION',
      retentionDescription: 'bounded mock evidence window',
      journalSearchLabel: 'ПОИСК СОБЫТИЙ',
      journalSearchPlaceholder: 'Action, target или reason',
      resultFilterLabel: 'РЕЗУЛЬТАТ',
      resultAll: 'Все',
      resultOk: 'OK',
      resultOpen: 'OPEN',
      resultError: 'ERROR',
      alertEyebrow: 'HEALTH SIGNALS',
      alertHeading: 'Сигналы для оператора',
      historyEyebrow: 'STATUS HISTORY',
      historyHeading: 'История снимков',
      eventsEyebrow: 'AUDIT EVENTS',
      eventsHeading: 'Безопасный журнал',
      noAlerts: 'Активных сигналов нет.',
      noHistory: 'История снимков пока недоступна.',
      noEvents: 'Событий по текущему фильтру нет.',
      historyState: 'Состояние',
      historyPeers: 'клиентов',
      historyTraffic: 'трафик',
      days: 'дн',
      exportReadyJson: 'JSON evidence подготовлен',
      exportReadyCsv: 'CSV evidence подготовлен',
      exportError: 'Не удалось подготовить evidence',
      filterEmpty: 'По текущему фильтру записей нет.',
      clientsHeading: 'Реестр клиентов',
      clientsSubtitle: 'Поиск, фильтры и dossier работают поверх frontend state.',
      records: 'записей',
      searchLabel: 'ПОИСК',
      searchPlaceholder: 'Имя, notes или tags',
      clearSearch: 'Очистить поиск',
      filterLabel: 'ФИЛЬТР',
      clearFilters: 'Сбросить',
      noResultsHeading: 'Ничего не найдено',
      noResultsCopy: 'Измените поисковый запрос или сбросьте фильтры.',
      noClientsHeading: 'Клиентов пока нет',
      noClientsCopy: 'Добавление появится после подключения lifecycle backend.',
      resetFilters: 'Сбросить фильтры',
      tableEyebrow: 'PEER REGISTRY',
      tableHeading: 'Клиенты',
      clientColumn: 'Клиент',
      statusColumn: 'Состояние',
      handshakeColumn: 'Handshake',
      lastActiveColumn: 'Последняя активность',
      trafficColumn: 'Всего трафика',
      actionColumn: 'Действия',
      openActions: 'Открыть действия для',
      actionOpen: 'Открыть',
      actionEdit: 'Редактировать metadata',
      actionConfig: 'Сформировать configuration',
      actionDisable: 'Отключить',
      actionEnable: 'Включить',
      actionDelete: 'Удалить',
      configAction: 'Сформировать configuration · preview',
      selectedClient: 'Клиент',
      cancel: 'Отмена',
      close: 'Закрыть',
      saveChanges: 'Сохранить изменения',
      editEyebrow: 'CLIENT METADATA / MOCK',
      editDialogTitle: 'Редактировать клиента',
      editDialogCopy: 'Изменения применяются только к frontend mock state и записываются в Journal.',
      closeEdit: 'Закрыть редактирование',
      editNameLabel: 'Имя клиента',
      editNotesLabel: 'Notes',
      editTagsLabel: 'Tags',
      editTagsPlaceholder: 'priority, review',
      editExpirationLabel: 'Истекает',
      editNameInvalid: 'Имя должно содержать 2–48 безопасных символов.',
      editNotesInvalid: 'Notes должны содержать не более 240 символов.',
      editTagsInvalid: 'Каждый tag должен содержать 1–24 безопасных символа.',
      editTagsTooMany: 'Можно указать не более пяти tags.',
      editExpirationInvalid: 'Укажите корректную дату в формате YYYY-MM-DD или оставьте поле пустым.',
      editAdapterError: 'Изменения клиента не были сохранены.',
      clientUpdated: 'Метаданные клиента обновлены',
      clientEnabled: 'Клиент включён в mock state',
      clientDisabled: 'Клиент отключён в mock state',
      clientDeleted: 'Mock record клиента удалён',
      statusAdapterError: 'Состояние клиента не было изменено.',
      deleteEyebrow: 'DESTRUCTIVE ACTION / MOCK',
      deleteDialogTitle: 'Удалить клиента?',
      deleteDialogCopy: 'Проверьте имя клиента и подтвердите удаление только из frontend mock state.',
      closeDelete: 'Закрыть удаление',
      deleteConfirm: 'Удалить mock record',
      deleteBoundary: 'Peer, ключи и production state не удаляются.',
      deleteAdapterError: 'Клиент не был удалён.',
      configEyebrow: 'CONFIGURATION / MOCK PREVIEW',
      configDialogTitle: 'Конфигурация клиента · preview',
      configDialogCopy: 'Показаны только синтетические QR и configuration placeholders. Реальные секреты не генерируются.',
      closeConfig: 'Закрыть preview конфигурации',
      configBoundary: 'UI READY / BACKEND STUB · MOCK DATA ONLY',
      configQrTab: 'QR',
      configTextTab: 'CONFIG',
      configSensitiveNote: 'В production configuration будет sensitive material; в этом prototype оно не создаётся.',
      copyConfig: 'Копировать',
      downloadMock: 'Скачать mock',
      configCopySuccess: 'Mock configuration скопирован',
      configDownloadReady: 'Mock configuration подготовлен',
      configAdapterError: 'Configuration preview не был подготовлен.',
      configForbiddenResult: 'Adapter вернул небезопасный configuration preview.',
      sortBy: 'Сортировать по',
      dossierEyebrow: 'SELECTED RECORD',
      dossierHeading: 'Досье клиента',
      closeDossier: 'Закрыть досье',
      dossierEmptyHeading: 'Клиент не выбран',
      dossierEmptyCopy: 'Выберите строку, чтобы открыть dossier.',
      lastHandshake: 'Last handshake',
      lastSeen: 'Last seen',
      createdAt: 'Создан',
      expiration: 'Истекает',
      trafficSection: 'TRAFFIC',
      totalTraffic: 'Всего',
      received: 'Получено',
      sent: 'Отправлено',
      metadataSection: 'METADATA',
      notes: 'Notes',
      tags: 'Tags',
      warnings: 'Warnings',
      noWarnings: 'Нет предупреждений',
      noNotes: 'Нет заметок',
      noTags: 'Нет tags',
      safeNote: 'Keys, endpoints and raw AWG properties are not shown.',
      configStub: 'Сформировать конфигурацию · BACKEND STUB',
      footerText: 'AWG CITA / PRODUCT SPRINT 4',
      footerMode: 'MOCK LIFECYCLE · FRONTEND STATE ONLY',
      ready: 'READY',
      loading: 'LOADING',
      error: 'ERROR',
      neverConnected: 'Никогда',
      justNow: 'только что',
      secondsAgo: 'с назад',
      minutesAgo: 'мин назад',
      hoursAgo: 'ч назад',
      daysAgo: 'дн назад',
      refreshSuccess: 'Данные обновлены',
      refreshError: 'Ошибка обновления',
      malformedResult: 'Adapter вернул некорректные данные',
      statusOnline: 'ONLINE',
      statusIdle: 'IDLE',
      statusStale: 'STALE',
      statusNever: 'NEVER',
      statusDisabled: 'DISABLED',
      loadedFixtures: 'FIXTURES_LOADED',
      refreshed: 'STATUS_REFRESHED',
      sourceMock: 'MOCK',
      ok: 'OK',
      openDossier: 'Открыть dossier для',
      activityEmpty: 'Событий пока нет.',
      previewEyebrow: 'CONTROLLED LIFECYCLE / PREVIEW',
      previewDialogTitle: 'Создание клиента · preview',
      previewDialogCopy: 'Проверка метаданных без создания peer, ключей, конфигурации или QR.',
      closePreview: 'Закрыть preview',
      previewStepDetails: 'Данные клиента',
      previewStepResult: 'Результат / Dry run',
      previewNameLabel: 'Имя клиента',
      previewNamePlaceholder: 'Например, Field Laptop',
      previewNameHint: '2–48 символов: буквы, цифры, пробел, точка, дефис или подчёркивание.',
      previewTagsLabel: 'Tags · необязательно',
      previewTagsPlaceholder: 'field, review',
      previewTagsHint: 'До 5 tags через запятую, без секретов и connection data.',
      previewSubmit: 'Запустить preview',
      previewCancel: 'Отмена',
      previewDone: 'Готово',
      previewResultHeading: 'Preview принят',
      previewResultCopy: 'Mock adapter проверил безопасные метаданные. Production lifecycle не вызывался.',
      previewResultId: 'Preview ID',
      previewResultName: 'Имя',
      previewResultTags: 'Tags',
      previewResultStatus: 'Статус',
      previewNoPeerCreated: 'NO PEER CREATED · KEYS / CONFIG / QR NOT GENERATED',
      previewNameRequired: 'Введите имя клиента.',
      previewNameInvalid: 'Имя должно содержать 2–48 безопасных символов.',
      previewTagsInvalid: 'Каждый tag должен содержать 1–24 безопасных символа.',
      previewTagsTooMany: 'Можно указать не более пяти tags.',
      previewAdapterError: 'Preview не был подготовлен.',
      realCreateError: 'Результат создания не подтверждён. Проверьте список клиентов перед повторной попыткой.',
      realQrError: 'QR не удалось отобразить; скачайте .conf вместо него.'
    },
    en: {
      consoleLabel: 'OPERATOR CONSOLE',
      navOverview: 'Overview',
      navClients: 'Clients',
      navJournal: 'Journal',
      mockBoundary: 'UI READY / BACKEND STUB',
      railBoundary: 'Mutations disabled',
      perimeter: 'LOCAL PERIMETER',
      summaryEyebrow: '01 — SUMMARY',
      titleLineOne: 'Management',
      titleLineTwo: 'node',
      subtitle: 'Safe operator telemetry for AmneziaWG.',
      refresh: 'Refresh',
      refreshInProgress: 'Refreshing…',
      addClient: 'Preview client',
      mutationBoundary: 'Live lifecycle mutations are disabled; this button opens a preview only.',
      overviewEyebrow: '01 / OVERVIEW',
      overviewHeading: 'Node state',
      lastRefresh: 'Last refresh',
      state: 'State',
      stateDescription: 'frontend state ready',
      active: 'Active',
      traffic: 'Session traffic',
      trafficDescription: 'RX + TX from the fixture dataset',
      attention: 'Attention',
      attentionDescription: 'stale / never / disabled',
      activityEyebrow: 'EVENT STREAM',
      activityHeading: 'Activity log',
      healthEyebrow: 'CONTROL PLANE',
      healthHeading: 'Health signals',
      totalPeers: 'Total clients',
      onlinePeers: 'Online',
      disabledPeers: 'Disabled',
      stalePeers: 'Stale',
      attentionPeers: 'Needs attention',
      adapterMode: 'Adapter',
      adapterMock: 'MOCK LIFECYCLE',
      clientsEyebrow: '02 / REGISTRY',
      journalEyebrow: '03 / OBSERVABILITY',
      journalHeading: 'Observability and audit',
      journalSubtitle: 'Status summaries, safe events, and evidence export without secrets.',
      exportJson: 'Export JSON',
      exportCsv: 'Export CSV',
      retentionLabel: 'RETENTION',
      retentionDescription: 'bounded mock evidence window',
      journalSearchLabel: 'EVENT SEARCH',
      journalSearchPlaceholder: 'Action, target, or reason',
      resultFilterLabel: 'RESULT',
      resultAll: 'All',
      resultOk: 'OK',
      resultOpen: 'OPEN',
      resultError: 'ERROR',
      alertEyebrow: 'HEALTH SIGNALS',
      alertHeading: 'Operator signals',
      historyEyebrow: 'STATUS HISTORY',
      historyHeading: 'Snapshot history',
      eventsEyebrow: 'AUDIT EVENTS',
      eventsHeading: 'Safe event log',
      noAlerts: 'No active signals.',
      noHistory: 'No status history is available yet.',
      noEvents: 'No events match the current filter.',
      historyState: 'State',
      historyPeers: 'clients',
      historyTraffic: 'traffic',
      days: 'd',
      exportReadyJson: 'JSON evidence prepared',
      exportReadyCsv: 'CSV evidence prepared',
      exportError: 'Evidence could not be prepared',
      filterEmpty: 'No records match the current filter.',
      clientsHeading: 'Client registry',
      clientsSubtitle: 'Search, filters, and the dossier operate on frontend state.',
      records: 'records',
      searchLabel: 'SEARCH',
      searchPlaceholder: 'Name, notes, or tags',
      clearSearch: 'Clear search',
      filterLabel: 'FILTER',
      clearFilters: 'Clear',
      noResultsHeading: 'Nothing found',
      noResultsCopy: 'Change the search query or clear the filters.',
      noClientsHeading: 'No clients yet',
      noClientsCopy: 'Creation becomes available after the lifecycle backend is connected.',
      resetFilters: 'Clear filters',
      tableEyebrow: 'PEER REGISTRY',
      tableHeading: 'Clients',
      clientColumn: 'Client',
      statusColumn: 'Status',
      handshakeColumn: 'Handshake',
      lastActiveColumn: 'Last active',
      trafficColumn: 'Total traffic',
      actionColumn: 'Actions',
      openActions: 'Open actions for',
      actionOpen: 'Open',
      actionEdit: 'Edit metadata',
      actionConfig: 'Generate configuration',
      actionDisable: 'Disable',
      actionEnable: 'Enable',
      actionDelete: 'Delete',
      configAction: 'Generate configuration · preview',
      selectedClient: 'Client',
      cancel: 'Cancel',
      close: 'Close',
      saveChanges: 'Save changes',
      editEyebrow: 'CLIENT METADATA / MOCK',
      editDialogTitle: 'Edit client',
      editDialogCopy: 'Changes apply only to frontend mock state and are written to the Journal.',
      closeEdit: 'Close edit dialog',
      editNameLabel: 'Client name',
      editNotesLabel: 'Notes',
      editTagsLabel: 'Tags',
      editTagsPlaceholder: 'priority, review',
      editExpirationLabel: 'Expiration',
      editNameInvalid: 'The name must contain 2–48 safe characters.',
      editNotesInvalid: 'Notes must be no longer than 240 characters.',
      editTagsInvalid: 'Each tag must contain 1–24 safe characters.',
      editTagsTooMany: 'Use no more than five tags.',
      editExpirationInvalid: 'Enter a valid YYYY-MM-DD date or leave the field empty.',
      editAdapterError: 'Client changes were not saved.',
      clientUpdated: 'Client metadata updated',
      clientEnabled: 'Client enabled in mock state',
      clientDisabled: 'Client disabled in mock state',
      clientDeleted: 'Client mock record deleted',
      statusAdapterError: 'The client state was not changed.',
      deleteEyebrow: 'DESTRUCTIVE ACTION / MOCK',
      deleteDialogTitle: 'Delete client?',
      deleteDialogCopy: 'Review the client name and confirm deletion from frontend mock state only.',
      closeDelete: 'Close delete dialog',
      deleteConfirm: 'Delete mock record',
      deleteBoundary: 'No peer, key material, or production state is deleted.',
      deleteAdapterError: 'The client was not deleted.',
      configEyebrow: 'CONFIGURATION / MOCK PREVIEW',
      configDialogTitle: 'Client configuration · preview',
      configDialogCopy: 'Only synthetic QR and configuration placeholders are shown. Real secrets are not generated.',
      closeConfig: 'Close configuration preview',
      configBoundary: 'UI READY / BACKEND STUB · MOCK DATA ONLY',
      configQrTab: 'QR',
      configTextTab: 'CONFIG',
      configSensitiveNote: 'Production configuration would contain sensitive material; this prototype does not create it.',
      copyConfig: 'Copy',
      downloadMock: 'Download mock',
      configCopySuccess: 'Mock configuration copied',
      configDownloadReady: 'Mock configuration prepared',
      configAdapterError: 'Configuration preview could not be prepared.',
      configForbiddenResult: 'The adapter returned an unsafe configuration preview.',
      sortBy: 'Sort by',
      dossierEyebrow: 'SELECTED RECORD',
      dossierHeading: 'Client dossier',
      closeDossier: 'Close dossier',
      dossierEmptyHeading: 'No client selected',
      dossierEmptyCopy: 'Select a row to open the dossier.',
      lastHandshake: 'Last handshake',
      lastSeen: 'Last seen',
      createdAt: 'Created',
      expiration: 'Expiration',
      trafficSection: 'TRAFFIC',
      totalTraffic: 'Total',
      received: 'Received',
      sent: 'Sent',
      metadataSection: 'METADATA',
      notes: 'Notes',
      tags: 'Tags',
      warnings: 'Warnings',
      noWarnings: 'No warnings',
      noNotes: 'No notes',
      noTags: 'No tags',
      safeNote: 'Keys, endpoints, and raw AWG properties are not shown.',
      configStub: 'Generate configuration · BACKEND STUB',
      footerText: 'AWG CITA / PRODUCT SPRINT 4',
      footerMode: 'MOCK LIFECYCLE · FRONTEND STATE ONLY',
      ready: 'READY',
      loading: 'LOADING',
      error: 'ERROR',
      neverConnected: 'Never',
      justNow: 'just now',
      secondsAgo: 's ago',
      minutesAgo: 'm ago',
      hoursAgo: 'h ago',
      daysAgo: 'd ago',
      refreshSuccess: 'Data refreshed',
      refreshError: 'Refresh failed',
      malformedResult: 'The adapter returned malformed data',
      statusOnline: 'ONLINE',
      statusIdle: 'IDLE',
      statusStale: 'STALE',
      statusNever: 'NEVER',
      statusDisabled: 'DISABLED',
      loadedFixtures: 'FIXTURES_LOADED',
      refreshed: 'STATUS_REFRESHED',
      sourceMock: 'MOCK',
      ok: 'OK',
      openDossier: 'Open dossier for',
      activityEmpty: 'No events yet.',
      previewEyebrow: 'CONTROLLED LIFECYCLE / PREVIEW',
      previewDialogTitle: 'Create client · preview',
      previewDialogCopy: 'Validate metadata without creating a peer, keys, configuration, or QR.',
      closePreview: 'Close preview',
      previewStepDetails: 'Client details',
      previewStepResult: 'Result / Dry run',
      previewNameLabel: 'Client name',
      previewNamePlaceholder: 'For example, Field Laptop',
      previewNameHint: '2–48 characters: letters, numbers, spaces, dot, dash, or underscore.',
      previewTagsLabel: 'Tags · optional',
      previewTagsPlaceholder: 'field, review',
      previewTagsHint: 'Up to 5 comma-separated tags; no secrets or connection data.',
      previewSubmit: 'Run preview',
      previewCancel: 'Cancel',
      previewDone: 'Done',
      previewResultHeading: 'Preview accepted',
      previewResultCopy: 'The mock adapter checked safe metadata. No production lifecycle call was made.',
      previewResultId: 'Preview ID',
      previewResultName: 'Name',
      previewResultTags: 'Tags',
      previewResultStatus: 'Status',
      previewNoPeerCreated: 'NO PEER CREATED · KEYS / CONFIG / QR NOT GENERATED',
      previewNameRequired: 'Enter a client name.',
      previewNameInvalid: 'The name must contain 2–48 safe characters.',
      previewTagsInvalid: 'Each tag must contain 1–24 safe characters.',
      previewTagsTooMany: 'Use no more than five tags.',
      previewAdapterError: 'Preview could not be prepared.',
      realCreateError: 'Creation outcome is uncertain. Check the client list before retrying.',
      realQrError: 'QR could not be rendered; download the .conf instead.'
    }
  };

  const t = (key) => translations[state.locale][key] || translations.en[key] || key;

  const fixtures = [
    {
      id: 'peer-atlas', name: 'Atlas Relay', status: 'ONLINE', lastHandshakeAt: ago(90 * 1000), lastSeenAt: ago(20 * 1000), createdAt: '2026-08-17', expiration: '2026-12-31', rxBytes: 8_431_616, txBytes: 4_923_392, notes: 'Primary office relay.', tags: ['priority', 'office'], warning: ''
    },
    {
      id: 'peer-boreal', name: 'Boreal Lab', status: 'IDLE', lastHandshakeAt: ago(22 * 60 * 1000), lastSeenAt: ago(22 * 60 * 1000), createdAt: '2026-08-21', expiration: '2027-01-15', rxBytes: 1_572_864, txBytes: 786_432, notes: 'Research workstation.', tags: ['lab'], warning: ''
    },
    {
      id: 'peer-cinder', name: 'Cinder Mobile', status: 'STALE', lastHandshakeAt: ago(3 * 24 * 60 * 60 * 1000), lastSeenAt: ago(3 * 24 * 60 * 60 * 1000), createdAt: '2026-07-02', expiration: '2026-10-02', rxBytes: 42_467_328, txBytes: 8_912_896, notes: 'Last seen during the field visit.', tags: ['mobile', 'field'], warning: 'Handshake is older than the operator threshold.'
    },
    {
      id: 'peer-delta', name: 'Delta New', status: 'NEVER', lastHandshakeAt: null, lastSeenAt: null, createdAt: '2026-09-21', expiration: '', rxBytes: 0, txBytes: 0, notes: 'Provisioned fixture with no handshake yet.', tags: ['new'], warning: 'Client has never connected.'
    },
    {
      id: 'peer-echo', name: 'Echo Disabled', status: 'DISABLED', lastHandshakeAt: ago(14 * 24 * 60 * 60 * 1000), lastSeenAt: ago(14 * 24 * 60 * 60 * 1000), createdAt: '2026-06-12', expiration: '2026-11-30', rxBytes: 2_621_440, txBytes: 1_310_720, notes: 'Temporarily disabled for review.', tags: ['hold'], warning: 'Lifecycle state is disabled.'
    },
    {
      id: 'peer-falkor', name: 'Falkor Heavy', status: 'ONLINE', lastHandshakeAt: ago(45 * 1000), lastSeenAt: ago(10 * 1000), createdAt: '2026-05-03', expiration: '2027-05-03', rxBytes: 41_523_912_704, txBytes: 8_013_348_864, notes: 'High-traffic synthetic peer.', tags: ['priority', 'high-traffic'], warning: ''
    },
    {
      id: 'peer-garnet', name: 'Garnet Remote', status: 'IDLE', lastHandshakeAt: ago(48 * 60 * 1000), lastSeenAt: ago(48 * 60 * 1000), createdAt: '2026-08-30', expiration: '2026-12-04', rxBytes: 28_311_552, txBytes: 14_155_776, notes: 'Remote operator laptop.', tags: ['remote'], warning: ''
    },
    {
      id: 'peer-harbor', name: 'Harbor Stale', status: 'STALE', lastHandshakeAt: ago(9 * 24 * 60 * 60 * 1000), lastSeenAt: ago(9 * 24 * 60 * 60 * 1000), createdAt: '2026-04-19', expiration: '2026-10-19', rxBytes: 5_767_168, txBytes: 2_883_584, notes: 'Keep for archive verification.', tags: ['archive', 'review'], warning: 'Expiration is approaching and handshake is stale.'
    },
    {
      id: 'peer-ivory', name: 'Ivory Expiring', status: 'ONLINE', lastHandshakeAt: ago(3 * 60 * 1000), lastSeenAt: ago(2 * 60 * 1000), createdAt: '2026-07-28', expiration: '2026-10-03', rxBytes: 734_003, txBytes: 367_001, notes: 'Synthetic expiry warning case.', tags: ['expiring'], warning: 'Expiration date is within the review window.'
    },
    {
      id: 'peer-juniper', name: 'Juniper Note', status: 'NEVER', lastHandshakeAt: null, lastSeenAt: null, createdAt: '2026-09-10', expiration: '2027-02-28', rxBytes: 0, txBytes: 0, notes: 'Awaiting device enrollment.', tags: ['onboarding', 'new'], warning: 'No session data is available.'
    }
  ];

  const observabilityFixtures = {
    schemaVersion: 1,
    retentionDays: 7,
    statusHistory: [
      { id: 'snapshot-001', checkedAt: ago(6 * 60 * 1000), state: 'OK', peerCount: 10, onlineCount: 3, attentionCount: 6, rxBytes: 42_871_808_000, txBytes: 9_103_774_000, reasonRu: 'Снимок собран без ошибок.', reasonEn: 'Snapshot collected without errors.' },
      { id: 'snapshot-002', checkedAt: ago(26 * 60 * 1000), state: 'OK', peerCount: 10, onlineCount: 3, attentionCount: 6, rxBytes: 42_642_113_000, txBytes: 9_020_113_000, reasonRu: 'Состояние источника стабильно.', reasonEn: 'Source state is stable.' },
      { id: 'snapshot-003', checkedAt: ago(46 * 60 * 1000), state: 'ERROR', peerCount: 10, onlineCount: 0, attentionCount: 10, rxBytes: 0, txBytes: 0, reasonRu: 'Один сборщик не вернул безопасный снимок.', reasonEn: 'One collector did not return a safe snapshot.' },
      { id: 'snapshot-004', checkedAt: ago(66 * 60 * 1000), state: 'OK', peerCount: 10, onlineCount: 3, attentionCount: 6, rxBytes: 42_401_001_000, txBytes: 8_994_671_000, reasonRu: 'Плановая проверка telemetry.', reasonEn: 'Scheduled telemetry check.' },
      { id: 'snapshot-005', checkedAt: ago(86 * 60 * 1000), state: 'OK', peerCount: 10, onlineCount: 3, attentionCount: 6, rxBytes: 42_184_663_000, txBytes: 8_922_005_000, reasonRu: 'Плановая проверка telemetry.', reasonEn: 'Scheduled telemetry check.' },
      { id: 'snapshot-006', checkedAt: ago(106 * 60 * 1000), state: 'OK', peerCount: 10, onlineCount: 3, attentionCount: 6, rxBytes: 41_991_448_000, txBytes: 8_811_010_000, reasonRu: 'Плановая проверка telemetry.', reasonEn: 'Scheduled telemetry check.' }
    ],
    auditEvents: [
      { id: 'event-001', timestamp: ago(6 * 60 * 1000), actor: 'SYSTEM', action: 'STATUS_REFRESHED', target: 'AWG node', result: 'OK', correlationId: 'corr-20260922-001', reasonRu: 'Плановая проверка telemetry.', reasonEn: 'Scheduled telemetry check.' },
      { id: 'event-002', timestamp: ago(18 * 60 * 1000), actor: 'SYSTEM', action: 'STALE_ALERT_OPENED', target: 'Cinder Mobile', result: 'OPEN', correlationId: 'corr-20260922-002', reasonRu: 'Handshake превышает операторский порог.', reasonEn: 'Handshake exceeds the operator threshold.' },
      { id: 'event-003', timestamp: ago(26 * 60 * 1000), actor: 'OPERATOR', action: 'REGISTRY_REVIEWED', target: 'Peer registry', result: 'OK', correlationId: 'corr-20260922-003', reasonRu: 'Проверка безопасных метаданных.', reasonEn: 'Safe metadata review.' },
      { id: 'event-004', timestamp: ago(46 * 60 * 1000), actor: 'SYSTEM', action: 'SNAPSHOT_FAILED', target: 'AWG node', result: 'ERROR', correlationId: 'corr-20260922-004', reasonRu: 'Источник не вернул безопасный снимок.', reasonEn: 'Source did not return a safe snapshot.' },
      { id: 'event-005', timestamp: ago(66 * 60 * 1000), actor: 'SYSTEM', action: 'RETENTION_CHECKED', target: 'Evidence window', result: 'OK', correlationId: 'corr-20260922-005', reasonRu: 'Окно хранения ограничено семью днями.', reasonEn: 'Retention window is bounded to seven days.' },
      { id: 'event-006', timestamp: ago(86 * 60 * 1000), actor: 'SYSTEM', action: 'STATUS_REFRESHED', target: 'AWG node', result: 'OK', correlationId: 'corr-20260922-006', reasonRu: 'Плановая проверка telemetry.', reasonEn: 'Scheduled telemetry check.' }
    ],
    alerts: [
      { id: 'alert-001', severity: 'WARNING', status: 'OPEN', code: 'STALE_PEER', target: 'Cinder Mobile · Harbor Stale', occurredAt: ago(18 * 60 * 1000), titleRu: 'Есть stale-клиенты', titleEn: 'Stale clients require review', detailRu: 'Два клиента превысили порог handshake.', detailEn: 'Two clients exceeded the handshake threshold.' },
      { id: 'alert-002', severity: 'ERROR', status: 'OPEN', code: 'SOURCE_FAILURE', target: 'AWG node', occurredAt: ago(46 * 60 * 1000), titleRu: 'Сбор снимка завершился ошибкой', titleEn: 'Snapshot collection failed', detailRu: 'Последний безопасный снимок сохранён; секреты не отображаются.', detailEn: 'The last safe snapshot is retained; secrets are not displayed.' },
      { id: 'alert-003', severity: 'INFO', status: 'OPEN', code: 'RETENTION_WINDOW', target: 'Evidence window', occurredAt: ago(6 * 60 * 1000), titleRu: 'Окно хранения ограничено', titleEn: 'Retention window is bounded', detailRu: 'Данные журнала доступны только в пределах семи дней.', detailEn: 'Journal data is available only within seven days.' }
    ]
  };

  const STATUS_LABELS = {
    ONLINE: 'statusOnline',
    IDLE: 'statusIdle',
    STALE: 'statusStale',
    NEVER: 'statusNever',
    DISABLED: 'statusDisabled'
  };

  const state = {
    currentView: ['clients', 'journal'].includes(window.location.hash.slice(1)) ? window.location.hash.slice(1) : 'overview',
    locale: 'ru',
    clients: [],
    statusHistory: [],
    auditEvents: [],
    alerts: [],
    retentionDays: 7,
    observabilitySchemaVersion: 1,
    selectedClientId: null,
    dossierOpen: false,
    hasVisitedClients: window.location.hash.slice(1) === 'clients',
    searchQuery: '',
    journalSearch: '',
    journalResultFilter: 'ALL',
    statusFilters: new Set(),
    sort: { key: 'name', direction: 'asc' },
    loading: true,
    refreshing: false,
    refreshFailures: 0,
    lastRefresh: null,
    error: '',
    activity: [],
    toasts: [],
    actionMenu: {
      open: false,
      clientId: null
    },
    createPreview: {
      open: false,
      step: 'form',
      name: '',
      tagsInput: '',
      tags: [],
      submitting: false,
      error: '',
      result: null
    },
    editClient: {
      open: false,
      clientId: null,
      name: '',
      notes: '',
      tagsInput: '',
      tags: [],
      expiration: '',
      submitting: false,
      error: ''
    },
    statusClient: {
      open: false,
      clientId: null,
      nextStatus: 'ONLINE',
      submitting: false
    },
    deleteClient: {
      open: false,
      clientId: null,
      submitting: false
    },
    configPreview: {
      open: false,
      clientId: null,
      tab: 'qr',
      loading: false,
      error: '',
      result: null
    }
  };
  let activeConfigPreviewRequest = null;

  class MockObservabilityAdapter {
    constructor() {
      this.snapshot = clone(observabilityFixtures);
    }

    async listObservability() {
      await wait(80);
      return clone(this.snapshot);
    }
  }

  class MockLifecycleAdapter {
    constructor() {
      this.records = clone(fixtures);
      this.observabilityAdapter = new MockObservabilityAdapter();
      this.failNextRefresh = false;
    }

    async listClients() {
      await wait(60);
      return clone(this.records);
    }

    async getClient(id) {
      await wait(25);
      return clone(this.records.find((client) => client.id === id) || null);
    }

    async refreshStatus() {
      await wait(120);
      if (this.failNextRefresh) {
        this.failNextRefresh = false;
        throw new Error('mock refresh failure');
      }
      return clone(this.records);
    }

    async listObservability() {
      return this.observabilityAdapter.listObservability();
    }

    async previewCreateClient(input) {
      await wait(70);
      return {
        schemaVersion: 1,
        previewId: `preview-${Date.now()}`,
        created: false,
        status: 'DRY_RUN',
        name: String(input?.name || ''),
        tags: Array.isArray(input?.tags) ? input.tags.slice(0, 5) : [],
        acknowledged: Boolean(input?.acknowledged),
        boundary: 'NO PEER CREATED'
      };
    }

    async updateClient(id, input) {
      await wait(70);
      const record = this.records.find((client) => client.id === id);
      if (!record) throw new Error('client_not_found');
      record.name = String(input?.name || record.name);
      record.notes = String(input?.notes || '');
      record.tags = Array.isArray(input?.tags) ? input.tags.slice(0, 5) : [];
      record.expiration = typeof input?.expiration === 'string' ? input.expiration : '';
      return clone(record);
    }

    async enableClient(id) {
      await wait(55);
      const record = this.records.find((client) => client.id === id);
      if (!record) throw new Error('client_not_found');
      record.status = 'ONLINE';
      if (record.warning === 'Lifecycle state is disabled.') record.warning = '';
      return clone(record);
    }

    async disableClient(id) {
      await wait(55);
      const record = this.records.find((client) => client.id === id);
      if (!record) throw new Error('client_not_found');
      record.status = 'DISABLED';
      record.warning = 'Lifecycle state is disabled.';
      return clone(record);
    }

    async deleteClient(id) {
      await wait(65);
      const index = this.records.findIndex((client) => client.id === id);
      if (index < 0) throw new Error('client_not_found');
      this.records.splice(index, 1);
      return { schemaVersion: 1, id, deleted: true };
    }

    async generateConfigurationPreview(id) {
      await wait(70);
      const record = this.records.find((client) => client.id === id);
      if (!record) throw new Error('client_not_found');
      const encodedName = encodeURIComponent(record.name);
      const configText = [
        '# MOCK CONFIGURATION',
        '# UI READY / BACKEND STUB',
        '[Client]',
        `Name = ${record.name}`,
        `Record = ${record.id}`,
        `Expiration = ${record.expiration || '[NONE]'}`,
        'Address = [NOT_GENERATED]',
        'KeyMaterial = [NOT_GENERATED]',
        'Transport = [MOCK_ONLY]'
      ].join('\n');
      return {
        schemaVersion: 1,
        previewId: `config-preview-${record.id}-${Date.now()}`,
        clientId: record.id,
        clientName: record.name,
        expiration: record.expiration || '',
        status: 'MOCK_PREVIEW',
        qrPayload: `AWG-CITA-MOCK-QR|client=${record.id}|name=${encodedName}|status=MOCK_PREVIEW`,
        configText
      };
    }

    async createClient() {
      throw new Error('backend_stub');
    }

    async updateClientBackendStub() {
      throw new Error('backend_stub');
    }

    async enableClientBackendStub() {
      throw new Error('backend_stub');
    }

    async disableClientBackendStub() {
      throw new Error('backend_stub');
    }

    async deleteClientBackendStub() {
      throw new Error('backend_stub');
    }

    async generateConfiguration() {
      throw new Error('backend_stub');
    }
  }

  class RealCanaryAdapter extends MockLifecycleAdapter {
    async request(path, body) {
      const response = await fetch(path, {
        method: body === undefined ? 'GET' : 'POST',
        credentials: 'same-origin',
        cache: 'no-store',
        headers: body === undefined ? {} : {
          'Content-Type': 'application/json',
          'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]')?.content || ''
        },
        body: body === undefined ? undefined : JSON.stringify(body)
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result?.error_code || 'canary_request_failed');
      return result;
    }

    async listClients() {
      const result = await this.request('/api/clients');
      if (result?.schema_version !== 1 || !Array.isArray(result.clients)) throw new Error('malformed_adapter_result');
      return result.clients;
    }

    async getClient(id) {
      return (await this.listClients()).find((client) => client.id === id) || null;
    }

    async refreshStatus() { return this.listClients(); }

    async listObservability() {
      return { schemaVersion: 1, retentionDays: 7, statusHistory: [], auditEvents: [], alerts: [] };
    }

    async mutate(operation, id) {
      const payload = { idempotencyKey: crypto.randomUUID() };
      if (operation === 'disable') payload.reason = 'operator_requested';
      if (operation === 'delete') payload.confirmation = true;
      const result = await this.request(`/api/clients/${encodeURIComponent(id)}/${operation}`, payload);
      if (result?.schema_version !== 1) throw new Error('malformed_adapter_result');
      return result;
    }

    async disableClient(id) { return (await this.mutate('disable', id)).client; }
    async enableClient(id) { return (await this.mutate('enable', id)).client; }
    async deleteClient(id) {
      const result = await this.mutate('delete', id);
      return { schemaVersion: 1, id: result.id, deleted: result.deleted };
    }
    async createClient(payload) { return this.request('/api/clients', payload); }
    async updateClient() { throw new Error('backend_stub'); }
    async generateConfigurationPreview(id) { return this.request(`/api/clients/${encodeURIComponent(id)}/config`); }
  }

  const shell = document.querySelector('.shell');
  const realCanary = shell?.dataset.runtime === 'real_canary';
  const testMode = !realCanary && shell?.dataset.testMode === 'true';
  const testAdapter = testMode ? window.__AWG_CITA_ADAPTER__ : null;
  const adapter = testAdapter || (realCanary ? new RealCanaryAdapter() : new MockLifecycleAdapter());
  const realCanaryCopy = {
    ru: {
      stateDescription: 'Состояние по AWG read-back',
      adapterMock: 'REAL CANARY',
      clientsSubtitle: 'Поиск, фильтры и карточки по данным awg-canary0.',
      configBoundary: 'Конфигурация доступна в меню клиента',
      previewResultCopy: 'Результат получен от awg-canary0.',
      footerText: 'AWG CITA / КАНАРНЫЙ КОНТУР',
      footerMode: 'REAL CANARY · AWG READ-BACK'
    },
    en: {
      stateDescription: 'State from AWG read-back',
      adapterMock: 'REAL CANARY',
      clientsSubtitle: 'Search, filters, and client details from awg-canary0.',
      configBoundary: 'Configuration is available in the client menu',
      previewResultCopy: 'Result received from awg-canary0.',
      footerText: 'AWG CITA / CANARY ENVIRONMENT',
      footerMode: 'REAL CANARY · AWG READ-BACK'
    }
  };

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
  }

  function formatBytes(value) {
    const bytes = Number(value) || 0;
    if (bytes < 1024) return `${bytes} B`;
    const units = ['KB', 'MB', 'GB', 'TB'];
    let amount = bytes;
    let unit = 'B';
    for (const nextUnit of units) {
      amount /= 1024;
      unit = nextUnit;
      if (amount < 1024) break;
    }
    const decimals = amount >= 100 ? 0 : amount >= 10 ? 1 : 2;
    return `${amount.toFixed(decimals)} ${unit}`;
  }

  function formatDate(value) {
    if (typeof value !== 'string' || !value) return '—';
    const dateValue = /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T12:00:00Z` : value;
    const date = new Date(dateValue);
    if (!Number.isFinite(date.getTime())) return '—';
    return new Intl.DateTimeFormat(state.locale === 'ru' ? 'ru-RU' : 'en-US', { year: 'numeric', month: 'short', day: 'numeric' }).format(date);
  }

  function formatDateTime(value) {
    if (!value) return '—';
    return new Intl.DateTimeFormat(state.locale === 'ru' ? 'ru-RU' : 'en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
  }

  function formatRelative(value) {
    if (!value) return t('neverConnected');
    const seconds = Math.max(0, Math.round((Date.now() - Date.parse(value)) / 1000));
    if (seconds < 10) return t('justNow');
    if (seconds < 60) return `${seconds} ${t('secondsAgo')}`;
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes} ${t('minutesAgo')}`;
    const hours = Math.round(minutes / 60);
    if (hours < 48) return `${hours} ${t('hoursAgo')}`;
    return `${Math.round(hours / 24)} ${t('daysAgo')}`;
  }

  function formatCount(count) {
    return new Intl.NumberFormat(state.locale === 'ru' ? 'ru-RU' : 'en-US').format(count);
  }

  function totalTraffic(client) {
    return (Number(client.rxBytes) || 0) + (Number(client.txBytes) || 0);
  }

  function statusClass(status) {
    return `status-${String(status).toLowerCase()}`;
  }

  function statusLabel(status) {
    return t(STATUS_LABELS[status] || status);
  }

  function addActivity(action, target, result = 'OK') {
    state.activity = [{ timestamp: new Date().toISOString(), actor: realCanary ? 'AWG-CITA' : t('sourceMock'), action, target, result }, ...state.activity].slice(0, 8);
  }

  function appendAuditEvent(event) {
    state.auditEvents = [event, ...state.auditEvents].slice(0, 120);
  }

  function showToast(message, type = 'info') {
    const toast = { id: `${Date.now()}-${Math.random()}`, message, type };
    state.toasts = [...state.toasts, toast].slice(-3);
    renderToasts();
    window.setTimeout(() => {
      state.toasts = state.toasts.filter((item) => item.id !== toast.id);
      renderToasts();
    }, 2600);
  }

  function applyTranslations() {
    document.documentElement.lang = state.locale;
    document.querySelectorAll('[data-i18n]').forEach((node) => {
      const key = node.dataset.i18n;
      node.textContent = (realCanary && realCanaryCopy[state.locale]?.[key]) || t(key);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach((node) => {
      node.placeholder = t(node.dataset.i18nPlaceholder);
    });
    document.querySelectorAll('[data-i18n-label]').forEach((node) => {
      node.setAttribute('aria-label', t(node.dataset.i18nLabel));
    });
    $('language-toggle').textContent = `${state.locale.toUpperCase()} ▾`;
  }

  function normalizeClients(value) {
    const allowedFields = [
      'id', 'name', 'status', 'lastHandshakeAt', 'lastSeenAt', 'createdAt', 'expiration',
      'rxBytes', 'txBytes', 'notes', 'tags', 'warning'
    ];
    if (!Array.isArray(value) || value.length > MAX_CLIENT_RECORDS) {
      throw new Error('malformed_adapter_result');
    }
    const ids = new Set();
    return value.map((client) => {
      if (!client || typeof client !== 'object' || Array.isArray(client)) throw new Error('malformed_adapter_result');
      const safe = Object.fromEntries(allowedFields.map((field) => [field, client[field]]));
      const validTimestamp = (timestamp) => timestamp === null || (
        typeof timestamp === 'string' && timestamp.length <= 40 &&
        /T/.test(timestamp) && /(?:Z|[+-]\d{2}:\d{2})$/.test(timestamp) && Number.isFinite(Date.parse(timestamp))
      );
      const validCreatedAt = safe.createdAt === null || (typeof safe.createdAt === 'string' && (
        isValidCalendarDate(safe.createdAt) || validTimestamp(safe.createdAt)
      ));
      const validTags = Array.isArray(safe.tags) && safe.tags.length <= 5 &&
        safe.tags.every((tag) => typeof tag === 'string' && PREVIEW_TAG_PATTERN.test(tag));
      const validNotes = typeof safe.notes === 'string' && safe.notes.length <= MAX_NOTES_LENGTH &&
        !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(safe.notes);
      const validWarning = typeof safe.warning === 'string' && safe.warning.length <= 240 &&
        !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(safe.warning);
      if (
        typeof safe.id !== 'string' || !/^peer-[A-Za-z0-9_-]{1,64}$/.test(safe.id) || ids.has(safe.id) ||
        typeof safe.name !== 'string' || safe.name !== safe.name.trim() || !PREVIEW_NAME_PATTERN.test(safe.name) ||
        !STATUS_ORDER.includes(safe.status) || !validTimestamp(safe.lastHandshakeAt) || !validTimestamp(safe.lastSeenAt) ||
        !validCreatedAt || !isValidExpiration(safe.expiration) ||
        !Number.isSafeInteger(safe.rxBytes) || safe.rxBytes < 0 ||
        !Number.isSafeInteger(safe.txBytes) || safe.txBytes < 0 ||
        !validNotes || !validTags || !validWarning
      ) {
        throw new Error('malformed_adapter_result');
      }
      ids.add(safe.id);
      return safe;
    });
  }

  function normalizePreviewResult(value) {
    const tags = Array.isArray(value?.tags) ? value.tags : [];
    const normalizedName = typeof value?.name === 'string' ? value.name.trim() : '';
    const validTags = tags.length <= 5 && tags.every((tag) => typeof tag === 'string' && tag === tag.trim() && PREVIEW_TAG_PATTERN.test(tag));
    if (!value || value.schemaVersion !== 1 || value.created !== false || value.status !== 'DRY_RUN' || value.acknowledged !== true || typeof value.previewId !== 'string' || !PREVIEW_ID_PATTERN.test(value.previewId) || typeof value.name !== 'string' || value.name !== normalizedName || !PREVIEW_NAME_PATTERN.test(normalizedName) || !Array.isArray(value.tags) || !validTags || value.boundary !== 'NO PEER CREATED') {
      throw new Error('malformed_preview_result');
    }
    return {
      schemaVersion: value.schemaVersion,
      previewId: value.previewId,
      created: false,
      status: 'DRY_RUN',
      name: normalizedName,
      tags: value.tags.slice(),
      acknowledged: true,
      boundary: 'NO PEER CREATED'
    };
  }

  function normalizeCreatedClient(value, expectedName, expectedTags) {
    const client = normalizeClients([value?.client])[0];
    const png = value?.qrDataUri;
    const encoded = typeof png === 'string' && /^data:image\/png;base64,([A-Za-z0-9+/]+={0,2})$/.exec(png);
    let bytes = null;
    try { if (encoded && png.length <= 131072) bytes = atob(encoded[1]); } catch (_error) { /* invalid image */ }
    if (value.schema_version !== 1 || value.oneTime !== false ||
        client.name !== expectedName || JSON.stringify(client.tags) !== JSON.stringify(expectedTags) ||
        typeof value.configText !== 'string' || !value.configText.length || value.configText.length > 16384 ||
        /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value.configText) ||
        !bytes || bytes.length < 24 || bytes.length > 98304 ||
        !bytes.startsWith('\x89PNG\r\n\x1a\n')) throw new Error('malformed_create_result');
    return { client, configText: value.configText, qrDataUri: png };
  }

  function isValidExpiration(value) {
    if (value === '') return true;
    if (typeof value !== 'string' || !EXPIRATION_PATTERN.test(value)) return false;
    const timestamp = Date.parse(`${value}T12:00:00Z`);
    return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === value && value >= '2020-01-01' && value <= '2100-12-31';
  }

  function isValidCalendarDate(value) {
    if (typeof value !== 'string' || !EXPIRATION_PATTERN.test(value)) return false;
    const timestamp = Date.parse(`${value}T00:00:00Z`);
    return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === value;
  }

  function normalizeUpdatedClient(value, expectedId = '') {
    const normalized = normalizeClients([value])[0];
    if (!normalized || (expectedId && normalized.id !== expectedId) || !PREVIEW_NAME_PATTERN.test(normalized.name.trim()) || normalized.name !== normalized.name.trim() || typeof normalized.id !== 'string' || !STATUS_ORDER.includes(normalized.status)) {
      throw new Error('malformed_client_result');
    }
    if (typeof normalized.notes !== 'string' || normalized.notes.length > MAX_NOTES_LENGTH || !isValidExpiration(normalized.expiration || '')) {
      throw new Error('malformed_client_result');
    }
    if (!Array.isArray(normalized.tags) || normalized.tags.length > 5 || normalized.tags.some((tag) => typeof tag !== 'string' || !PREVIEW_TAG_PATTERN.test(tag))) {
      throw new Error('malformed_client_result');
    }
    return normalized;
  }

  function normalizeDeleteResult(value, id) {
    if (!value || value.schemaVersion !== 1 || value.id !== id || value.deleted !== true) throw new Error('malformed_delete_result');
    return { schemaVersion: 1, id, deleted: true };
  }

  function normalizeConfigurationPreview(value, expectedClient) {
    const safeName = typeof value?.clientName === 'string' ? value.clientName.trim() : '';
    const safeQr = typeof value?.qrPayload === 'string' ? value.qrPayload : '';
    const safeConfig = typeof value?.configText === 'string' ? value.configText : '';
    const validClientId = typeof value?.clientId === 'string' && /^peer-[A-Za-z0-9_-]{1,64}$/.test(value.clientId);
    const expectedId = expectedClient?.id;
    const expectedName = expectedClient?.name;
    const expectedExpiration = typeof expectedClient?.expiration === 'string' ? expectedClient.expiration : '';
    const expectedQr = typeof expectedId === 'string' && typeof expectedName === 'string'
      ? `AWG-CITA-MOCK-QR|client=${expectedId}|name=${encodeURIComponent(expectedName)}|status=MOCK_PREVIEW`
      : '';
    const expectedConfig = typeof expectedId === 'string' && typeof expectedName === 'string'
      ? [
        '# MOCK CONFIGURATION',
        '# UI READY / BACKEND STUB',
        '[Client]',
        `Name = ${expectedName}`,
        `Record = ${expectedId}`,
        `Expiration = ${expectedExpiration || '[NONE]'}`,
        'Address = [NOT_GENERATED]',
        'KeyMaterial = [NOT_GENERATED]',
        'Transport = [MOCK_ONLY]'
      ].join('\n')
      : '';
    const validExpectedClient = typeof expectedId === 'string' && /^peer-[A-Za-z0-9_-]{1,64}$/.test(expectedId) &&
      typeof expectedName === 'string' && expectedName === expectedName.trim() && PREVIEW_NAME_PATTERN.test(expectedName) &&
      isValidExpiration(expectedExpiration);
    const valid = Boolean(value) && Boolean(expectedClient) && validExpectedClient &&
      value.schemaVersion === 1 && typeof value.previewId === 'string' && CONFIG_PREVIEW_ID_PATTERN.test(value.previewId) &&
      validClientId && value.clientId === expectedId && PREVIEW_NAME_PATTERN.test(safeName) &&
      safeName === value.clientName && safeName === expectedName && value.expiration === expectedExpiration &&
      isValidExpiration(typeof value.expiration === 'string' ? value.expiration : '') && value.status === 'MOCK_PREVIEW' &&
      safeQr === expectedQr && safeQr.length <= 320 && safeConfig === expectedConfig && safeConfig.length <= 2400;
    if (!valid) throw new Error('malformed_configuration_preview');
    return {
      schemaVersion: 1,
      previewId: value.previewId,
      clientId: value.clientId,
      clientName: safeName,
      expiration: value.expiration || '',
      status: 'MOCK_PREVIEW',
      qrPayload: safeQr,
      configText: safeConfig
    };
  }

  function normalizeObservability(value) {
    if (!value || !Array.isArray(value.statusHistory) || !Array.isArray(value.auditEvents) || !Array.isArray(value.alerts)) {
      throw new Error('malformed_observability_result');
    }
    if (value.schemaVersion !== 1) {
      throw new Error('unsupported_observability_schema');
    }
    return {
      schemaVersion: value.schemaVersion,
      retentionDays: Number.isFinite(Number(value.retentionDays)) ? Math.max(1, Math.min(30, Number(value.retentionDays))) : 7,
      statusHistory: value.statusHistory.slice(0, 60).map((item) => ({
        id: typeof item.id === 'string' ? item.id : `snapshot-${Math.random()}`,
        checkedAt: typeof item.checkedAt === 'string' ? item.checkedAt : null,
        state: ['OK', 'ERROR'].includes(item.state) ? item.state : 'UNKNOWN',
        peerCount: Number(item.peerCount) || 0,
        onlineCount: Number(item.onlineCount) || 0,
        attentionCount: Number(item.attentionCount) || 0,
        rxBytes: Number(item.rxBytes) || 0,
        txBytes: Number(item.txBytes) || 0,
        reasonRu: typeof item.reasonRu === 'string' ? item.reasonRu : '',
        reasonEn: typeof item.reasonEn === 'string' ? item.reasonEn : ''
      })),
      auditEvents: value.auditEvents.slice(0, 120).map((item) => ({
        id: typeof item.id === 'string' ? item.id : `event-${Math.random()}`,
        timestamp: typeof item.timestamp === 'string' ? item.timestamp : null,
        actor: typeof item.actor === 'string' ? item.actor : 'SYSTEM',
        action: typeof item.action === 'string' ? item.action : 'UNKNOWN_EVENT',
        target: typeof item.target === 'string' ? item.target : 'AWG node',
        result: ['OK', 'OPEN', 'ERROR', 'DRY_RUN'].includes(item.result) ? item.result : 'OPEN',
        correlationId: typeof item.correlationId === 'string' ? item.correlationId : 'corr-unavailable',
        reasonRu: typeof item.reasonRu === 'string' ? item.reasonRu : '',
        reasonEn: typeof item.reasonEn === 'string' ? item.reasonEn : ''
      })),
      alerts: value.alerts.slice(0, 30).map((item) => ({
        id: typeof item.id === 'string' ? item.id : `alert-${Math.random()}`,
        severity: ['INFO', 'WARNING', 'ERROR'].includes(item.severity) ? item.severity : 'INFO',
        status: typeof item.status === 'string' ? item.status : 'OPEN',
        code: typeof item.code === 'string' ? item.code : 'UNCLASSIFIED',
        target: typeof item.target === 'string' ? item.target : 'AWG node',
        occurredAt: typeof item.occurredAt === 'string' ? item.occurredAt : null,
        titleRu: typeof item.titleRu === 'string' ? item.titleRu : '',
        titleEn: typeof item.titleEn === 'string' ? item.titleEn : '',
        detailRu: typeof item.detailRu === 'string' ? item.detailRu : '',
        detailEn: typeof item.detailEn === 'string' ? item.detailEn : ''
      }))
    };
  }

  function localizedField(item, field) {
    const localized = item?.[`${field}${state.locale === 'ru' ? 'Ru' : 'En'}`];
    return localized || item?.[field] || '';
  }

  function getVisibleClients() {
    const query = state.searchQuery.trim().toLocaleLowerCase();
    const filtered = state.clients.filter((client) => {
      const haystack = [client.name, client.notes, ...(client.tags || [])].join(' ').toLocaleLowerCase();
      const matchesQuery = !query || haystack.includes(query);
      const matchesStatus = state.statusFilters.size === 0 || state.statusFilters.has(client.status);
      return matchesQuery && matchesStatus;
    });
    return filtered.sort((left, right) => {
      let comparison = 0;
      if (state.sort.key === 'name') comparison = left.name.localeCompare(right.name);
      if (state.sort.key === 'status') comparison = STATUS_RANK[left.status] - STATUS_RANK[right.status];
      if (state.sort.key === 'handshake') comparison = (Date.parse(left.lastHandshakeAt || '1970-01-01') || 0) - (Date.parse(right.lastHandshakeAt || '1970-01-01') || 0);
      if (state.sort.key === 'totalTraffic') comparison = totalTraffic(left) - totalTraffic(right);
      if (comparison === 0) comparison = left.name.localeCompare(right.name);
      return state.sort.direction === 'asc' ? comparison : comparison * -1;
    });
  }

  function reconcileSelection(visibleClients) {
    if (state.selectedClientId && !visibleClients.some((client) => client.id === state.selectedClientId)) {
      state.selectedClientId = null;
      state.dossierOpen = false;
    }
    if (state.selectedClientId && !state.clients.some((client) => client.id === state.selectedClientId)) {
      state.selectedClientId = null;
      state.dossierOpen = false;
    }
  }

  function renderNavigation() {
    document.querySelectorAll('[data-view]').forEach((button) => {
      const active = button.dataset.view === state.currentView;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-current', active ? 'page' : 'false');
    });
    document.querySelectorAll('[data-view-panel]').forEach((panel) => {
      panel.hidden = panel.dataset.viewPanel !== state.currentView;
    });
  }

  function renderConnection() {
    const connection = $('connection-state');
    const loading = state.loading || state.refreshing;
    const status = state.error ? 'error' : loading ? 'loading' : 'ready';
    connection.dataset.state = status;
    connection.textContent = `● ${t(status)}`;
    connection.className = `connection-state connection-${status}`;
    $('refresh-button').disabled = loading;
    $('refresh-button').textContent = loading && state.refreshing ? t('refreshInProgress') : t('refresh');
    $('app').setAttribute('aria-busy', String(loading));
  }

  function renderOverview() {
    const loaded = !state.loading && !state.error;
    const total = state.clients.length;
    const online = state.clients.filter((client) => client.status === 'ONLINE').length;
    const disabled = state.clients.filter((client) => client.status === 'DISABLED').length;
    const stale = state.clients.filter((client) => client.status === 'STALE').length;
    const attention = state.clients.filter((client) => ['STALE', 'NEVER', 'DISABLED'].includes(client.status) || client.warning).length;
    const traffic = state.clients.reduce((sum, client) => sum + totalTraffic(client), 0);
    $('metric-state').textContent = loaded ? t('ready') : state.error ? t('error') : '—';
    $('metric-online').textContent = loaded ? formatCount(online) : '—';
    $('metric-online-detail').textContent = loaded ? `${formatCount(total)} ${t('records')}` : '—';
    $('metric-traffic').textContent = loaded ? formatBytes(traffic) : '—';
    $('metric-attention').textContent = loaded ? formatCount(attention) : '—';
    $('health-total').textContent = loaded ? formatCount(total) : '—';
    $('health-online').textContent = loaded ? formatCount(online) : '—';
    $('health-disabled').textContent = loaded ? formatCount(disabled) : '—';
    $('health-stale').textContent = loaded ? formatCount(stale) : '—';
    $('health-attention').textContent = loaded ? formatCount(attention) : '—';
    $('last-refresh').textContent = state.lastRefresh ? formatDateTime(state.lastRefresh) : '—';
    $('activity-count').textContent = formatCount(state.activity.length);
    if (!state.activity.length) {
      $('activity-list').innerHTML = `<div class="inline-empty">${escapeHtml(t('activityEmpty'))}</div>`;
    } else {
      $('activity-list').innerHTML = state.activity.map((event) => `<div class="activity-row"><span class="activity-dot" aria-hidden="true"></span><div><strong>${escapeHtml(event.action)}</strong><span>${escapeHtml(event.target)} · ${escapeHtml(event.actor)}</span></div><time>${escapeHtml(formatDateTime(event.timestamp))}</time></div>`).join('');
    }
  }

  function renderFilterControls() {
    const counts = Object.fromEntries(STATUS_ORDER.map((status) => [status, state.clients.filter((client) => client.status === status).length]));
    $('client-search').value = state.searchQuery;
    document.querySelectorAll('[data-status-filter]').forEach((button) => {
      const active = state.statusFilters.has(button.dataset.statusFilter);
      button.setAttribute('aria-pressed', String(active));
      button.classList.toggle('is-active', active);
    });
    document.querySelectorAll('[data-filter-count]').forEach((node) => {
      node.textContent = formatCount(counts[node.dataset.filterCount] || 0);
    });
    $('clear-search').hidden = !state.searchQuery;
    $('clear-filters').disabled = !state.searchQuery && state.statusFilters.size === 0;
  }

  function renderTableHeaders() {
    const labels = { name: t('clientColumn'), status: t('statusColumn'), handshake: t('handshakeColumn'), totalTraffic: t('trafficColumn') };
    document.querySelectorAll('[data-sort-col]').forEach((header) => {
      const key = header.dataset.sortCol;
      const button = header.querySelector('[data-sort-key]');
      if (!button) return;
      const active = state.sort.key === key;
      header.setAttribute('aria-sort', active ? (state.sort.direction === 'asc' ? 'ascending' : 'descending') : 'none');
      button.setAttribute('aria-label', `${t('sortBy')} ${labels[key] || key}`);
      button.querySelector('.sort-indicator').textContent = active ? (state.sort.direction === 'asc' ? '↑' : '↓') : '↕';
      button.classList.toggle('is-active', active);
    });
  }

  function renderRows(visibleClients) {
    const body = $('client-rows');
    if (state.loading) {
      body.innerHTML = Array.from({ length: 6 }, () => '<tr class="skeleton-row"><td colspan="6"><span></span></td></tr>').join('');
      return;
    }
    if (!visibleClients.length) {
      body.innerHTML = '';
      return;
    }
    body.innerHTML = visibleClients.map((client) => {
      const selected = client.id === state.selectedClientId;
      const tags = (client.tags || []).slice(0, 2).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join('');
      return `<tr class="client-row${selected ? ' is-selected' : ''}" data-client-id="${escapeHtml(client.id)}" tabindex="0" aria-selected="${selected}">
        <td><div class="client-cell"><span class="client-glyph" aria-hidden="true">${escapeHtml(client.name.slice(0, 1).toUpperCase())}</span><div><strong>${escapeHtml(client.name)}</strong><span class="mono client-id">${escapeHtml(client.id)}</span><div class="row-tags">${tags}</div></div></div></td>
        <td><span class="status-pill ${statusClass(client.status)}"><span class="status-dot" aria-hidden="true"></span>${escapeHtml(statusLabel(client.status))}</span></td>
        <td class="mono">${escapeHtml(formatDateTime(client.lastHandshakeAt))}</td>
        <td>${escapeHtml(formatRelative(client.lastSeenAt))}</td>
        <td><div class="traffic-cell"><strong>${escapeHtml(formatBytes(totalTraffic(client)))}</strong><small>RX ${escapeHtml(formatBytes(client.rxBytes))} · TX ${escapeHtml(formatBytes(client.txBytes))}</small></div></td>
        <td><button class="row-actions-toggle row-open" type="button" data-action-menu-toggle="${escapeHtml(client.id)}" aria-haspopup="menu" aria-expanded="${state.actionMenu.open && state.actionMenu.clientId === client.id}" aria-controls="client-actions-menu" aria-label="${escapeHtml(t('openActions'))} ${escapeHtml(client.name)}">⋯</button></td>
      </tr>`;
    }).join('');
  }

  function renderClients(visibleClients) {
    renderFilterControls();
    renderTableHeaders();
    renderRows(visibleClients);
    $('client-count').textContent = formatCount(visibleClients.length);
    $('visible-count').textContent = `${formatCount(visibleClients.length)} / ${formatCount(state.clients.length)}`;
    const noClients = !state.loading && state.clients.length === 0;
    const noResults = !state.loading && state.clients.length > 0 && visibleClients.length === 0;
    $('clients-empty').hidden = !(noClients || noResults);
    $('clients-empty-heading').textContent = t(noClients ? 'noClientsHeading' : 'noResultsHeading');
    $('clients-empty-copy').textContent = t(noClients ? 'noClientsCopy' : 'noResultsCopy');
    $('reset-empty').hidden = noClients;
  }

  function renderDossier() {
    const selected = state.clients.find((client) => client.id === state.selectedClientId) || null;
    const dossier = $('client-dossier');
    const narrow = window.matchMedia('(max-width: 780px)').matches;
    const visible = Boolean(selected) && (!narrow || state.dossierOpen);
    dossier.classList.toggle('is-open', visible);
    dossier.setAttribute('aria-hidden', String(!visible));
    $('dossier-empty').hidden = Boolean(selected);
    $('dossier-content').hidden = !selected;
    if (!selected) return;
    $('dossier-client-name').textContent = selected.name;
    $('dossier-client-id').textContent = selected.id;
    $('dossier-status').className = `status-pill ${statusClass(selected.status)}`;
    $('dossier-status').textContent = statusLabel(selected.status);
    $('dossier-handshake').textContent = selected.lastHandshakeAt ? formatDateTime(selected.lastHandshakeAt) : t('neverConnected');
    $('dossier-last-seen').textContent = selected.lastSeenAt ? `${formatRelative(selected.lastSeenAt)} · ${formatDateTime(selected.lastSeenAt)}` : t('neverConnected');
    $('dossier-created').textContent = formatDate(selected.createdAt);
    $('dossier-expiration').textContent = selected.expiration ? formatDate(selected.expiration) : '—';
    $('dossier-total').textContent = formatBytes(totalTraffic(selected));
    $('dossier-rx').textContent = formatBytes(selected.rxBytes);
    $('dossier-tx').textContent = formatBytes(selected.txBytes);
    $('dossier-notes').textContent = selected.notes || t('noNotes');
    $('dossier-tags').innerHTML = selected.tags?.length ? selected.tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join('') : `<span class="muted">${escapeHtml(t('noTags'))}</span>`;
    $('dossier-warning').textContent = selected.warning || t('noWarnings');
    $('dossier-warning').classList.toggle('is-muted', !selected.warning);
  }

  function getAlerts() {
    const alerts = [...state.alerts];
    if (state.refreshFailures >= 2 && !alerts.some((alert) => alert.code === 'REFRESH_FAILURE')) {
      alerts.unshift({
        id: 'runtime-refresh-failure',
        severity: 'ERROR',
        status: 'OPEN',
        code: 'REFRESH_FAILURE',
        target: 'Frontend refresh',
        occurredAt: new Date().toISOString(),
        titleRu: 'Последнее обновление завершилось ошибкой',
        titleEn: 'The latest refresh failed',
        detailRu: `Неудачных попыток: ${state.refreshFailures}.`,
        detailEn: `Failed attempts: ${state.refreshFailures}.`
      });
    }
    return alerts;
  }

  function getVisibleAuditEvents() {
    const query = state.journalSearch.trim().toLocaleLowerCase();
    return state.auditEvents.filter((event) => {
      const haystack = [event.actor, event.action, event.target, event.correlationId, event.reasonRu, event.reasonEn].join(' ').toLocaleLowerCase();
      const matchesQuery = !query || haystack.includes(query);
      const matchesResult = state.journalResultFilter === 'ALL' || event.result === state.journalResultFilter;
      return matchesQuery && matchesResult;
    });
  }

  function renderJournal() {
    const alerts = getAlerts();
    const visibleEvents = getVisibleAuditEvents();
    $('journal-search').value = state.journalSearch;
    $('journal-result-filter').value = state.journalResultFilter;
    $('journal-retention').textContent = `${formatCount(state.retentionDays)} ${t('days')}`;
    $('alert-count').textContent = formatCount(alerts.length);
    $('history-count').textContent = formatCount(state.statusHistory.length);
    $('event-count').textContent = `${formatCount(visibleEvents.length)} / ${formatCount(state.auditEvents.length)}`;
    $('export-json').disabled = state.loading || !state.auditEvents.length;
    $('export-csv').disabled = state.loading || !state.auditEvents.length;

    $('journal-alerts').innerHTML = alerts.length ? alerts.map((alert) => `<article class="alert-card alert-${escapeHtml(alert.severity.toLowerCase())}">
      <div class="alert-severity" aria-hidden="true">${escapeHtml(alert.severity)}</div>
      <div class="alert-copy"><strong>${escapeHtml(localizedField(alert, 'title'))}</strong><span>${escapeHtml(localizedField(alert, 'detail'))}</span><small>${escapeHtml(alert.target)} · ${escapeHtml(formatDateTime(alert.occurredAt))}</small></div>
      <code>${escapeHtml(alert.code)}</code>
    </article>`).join('') : `<div class="inline-empty">${escapeHtml(t('noAlerts'))}</div>`;

    $('journal-history').innerHTML = state.statusHistory.length ? state.statusHistory.map((snapshot) => `<div class="history-row">
      <span class="history-dot history-${escapeHtml(snapshot.state.toLowerCase())}" aria-hidden="true"></span>
      <div class="history-copy"><strong>${escapeHtml(snapshot.state)}</strong><span>${escapeHtml(formatCount(snapshot.peerCount))} ${escapeHtml(t('historyPeers'))} · ${escapeHtml(formatCount(snapshot.onlineCount))} online · ${escapeHtml(formatBytes(snapshot.rxBytes + snapshot.txBytes))} ${escapeHtml(t('historyTraffic'))}</span><small>${escapeHtml(localizedField(snapshot, 'reason'))}</small></div>
      <time>${escapeHtml(formatDateTime(snapshot.checkedAt))}</time>
    </div>`).join('') : `<div class="inline-empty">${escapeHtml(t('noHistory'))}</div>`;

    $('journal-events').innerHTML = visibleEvents.length ? visibleEvents.map((event) => `<article class="audit-row">
      <div class="audit-copy"><strong>${escapeHtml(event.action)}</strong><span>${escapeHtml(event.target)} · ${escapeHtml(event.actor)}</span><small>${escapeHtml(localizedField(event, 'reason'))}</small></div>
      <div class="audit-meta"><span class="event-result event-result-${escapeHtml(event.result.toLowerCase())}">${escapeHtml(event.result)}</span><time>${escapeHtml(formatDateTime(event.timestamp))}</time><code>${escapeHtml(event.correlationId)}</code></div>
    </article>`).join('') : `<div class="inline-empty">${escapeHtml(state.journalSearch || state.journalResultFilter !== 'ALL' ? t('filterEmpty') : t('noEvents'))}</div>`;
  }

  function safeEvidencePayload() {
    return {
      schema_version: state.observabilitySchemaVersion,
      generated_at: new Date().toISOString(),
      runtime: 'mock_observability',
      retention_days: state.retentionDays,
      alerts: getAlerts().map((alert) => ({
        id: alert.id,
        severity: alert.severity,
        status: alert.status,
        code: alert.code,
        target: alert.target,
        occurred_at: alert.occurredAt,
        title: localizedField(alert, 'title'),
        detail: localizedField(alert, 'detail')
      })),
      status_history: state.statusHistory.map((snapshot) => ({
        id: snapshot.id,
        checked_at: snapshot.checkedAt,
        state: snapshot.state,
        peer_count: snapshot.peerCount,
        online_count: snapshot.onlineCount,
        attention_count: snapshot.attentionCount,
        rx_bytes: snapshot.rxBytes,
        tx_bytes: snapshot.txBytes,
        reason: localizedField(snapshot, 'reason')
      })),
      audit_events: state.auditEvents.map((event) => ({
        id: event.id,
        timestamp: event.timestamp,
        actor: event.actor,
        action: event.action,
        target: event.target,
        result: event.result,
        correlation_id: event.correlationId,
        reason: localizedField(event, 'reason')
      }))
    };
  }

  function csvEscape(value) {
    const text = String(value ?? '');
    return `"${text.replace(/"/g, '""')}"`;
  }

  function downloadEvidence(format) {
    try {
      const payload = safeEvidencePayload();
      let content;
      let mime;
      let extension;
      if (format === 'csv') {
        const header = ['schema_version', 'generated_at', 'record_type', 'timestamp', 'actor', 'action', 'target', 'result', 'correlation_id', 'reason'];
        const rows = payload.audit_events.map((event) => [payload.schema_version, payload.generated_at, 'audit_event', event.timestamp, event.actor, event.action, event.target, event.result, event.correlation_id, event.reason]);
        content = [header, ...rows].map((row) => row.map(csvEscape).join(',')).join('\n');
        mime = 'text/csv;charset=utf-8';
        extension = 'csv';
      } else {
        content = JSON.stringify(payload, null, 2);
        mime = 'application/json;charset=utf-8';
        extension = 'json';
      }
      const blob = new Blob([content], { type: mime });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `awg-cita-evidence-${extension}-${new Date().toISOString().slice(0, 10)}.${extension}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      showToast(extension === 'json' ? t('exportReadyJson') : t('exportReadyCsv'), 'success');
    } catch (_error) {
      showToast(t('exportError'), 'error');
    }
  }

  function renderGlobalError() {
    const error = $('global-error');
    error.hidden = !state.error;
    error.textContent = state.error;
  }

  function renderToasts() {
    $('toast-region').innerHTML = state.toasts.map((toast) => `<div class="toast toast-${escapeHtml(toast.type)}" role="status"><span class="toast-mark" aria-hidden="true">${toast.type === 'success' ? '✓' : '!'}</span>${escapeHtml(toast.message)}</div>`).join('');
  }

  async function renderCreatedQr(result) {
    const canvas = $('create-qr');
    const data = atob(result.qrDataUri.slice('data:image/png;base64,'.length));
    const bytes = Uint8Array.from(data, character => character.charCodeAt(0));
    try {
      const bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/png' }));
      if (state.createPreview.result !== result || !state.createPreview.open) { bitmap.close(); return; }
      const context = canvas.getContext('2d');
      context.imageSmoothingEnabled = false;
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      bitmap.close();
      canvas.dataset.rendered = 'true';
    } catch (_error) {
      if (state.createPreview.result === result && state.createPreview.open) {
        showToast(t('realQrError'), 'error');
      }
    }
  }

  function renderCreatePreview() {
    const wizard = state.createPreview;
    const modal = $('create-preview-modal');
    modal.hidden = !wizard.open;
    modal.setAttribute('aria-hidden', String(!wizard.open));
    document.body.classList.toggle('modal-open', wizard.open || state.editClient.open || state.deleteClient.open || state.configPreview.open);
    $('preview-step-form').hidden = !wizard.open || wizard.step !== 'form';
    $('preview-step-result').hidden = !wizard.open || wizard.step !== 'result';
    $('preview-form-error').hidden = !wizard.error;
    $('preview-form-error').textContent = wizard.error ? t(wizard.error) : '';
    $('preview-name').value = wizard.name;
    $('preview-tags').value = wizard.tagsInput;
    $('preview-cancel').hidden = !wizard.open || wizard.step === 'result';
    $('preview-submit').hidden = !wizard.open || wizard.step !== 'form';
    $('preview-done').hidden = !wizard.open || wizard.step !== 'result';
    $('preview-submit').disabled = wizard.submitting;
    if (realCanary) {
      const ru = state.locale === 'ru';
      const labels = ru ? {
        button: 'Создать клиента', title: 'Создание клиента · реальный peer', intro: 'Создание peer для AmneziaWG 3.1 на awg-canary0.',
        submit: 'Создать peer',
        result: 'Клиент создан', status: 'Статус', warning: 'Конфигурация доступна в меню клиента. Для подключения используйте AmneziaWG 3.1.',
        config: 'Конфигурация · приватная', qr: 'QR с приватной конфигурацией для совместимых сканеров; совместимость не проверена',
        copy: 'Копировать', download: 'Скачать .conf · рекомендуется', boundary: 'Реальный peer создан · сохраните конфигурацию сейчас'
      } : {
        button: 'Create client', title: 'Create client · real peer', intro: 'Creates an AmneziaWG 3.1 peer on awg-canary0.',
        submit: 'Create peer',
        result: 'Client created', status: 'Status', warning: 'Configuration is available in the client menu. Connect with AmneziaWG 3.1.',
        config: 'Configuration · private', qr: 'QR containing private configuration for compatible scanners; compatibility unverified',
        copy: 'Copy', download: 'Download .conf · recommended', boundary: 'Real peer created · save configuration now'
      };
      $('add-client-button').textContent = labels.button;
      $('preview-dialog-title').textContent = labels.title;
      $('preview-dialog-copy').textContent = labels.intro;
      $('preview-submit').textContent = labels.submit;
      document.querySelector('#preview-step-result h3').textContent = labels.result;
      document.querySelector('#preview-step-result .modal-copy').textContent = labels.warning;
      document.querySelector('[data-i18n="previewResultId"]').textContent = 'Peer ID';
      document.querySelector('[data-i18n="previewResultStatus"]').textContent = labels.status;
      $('create-one-time-warning').textContent = labels.warning;
      document.querySelector('[for="create-config-text"] span').textContent = labels.config;
      $('create-qr').setAttribute('aria-label', labels.qr);
      $('create-qr-caption').textContent = ru ? 'QR содержит приватную .conf для совместимых сканеров. Совместимость не проверена; рекомендуем скачать .conf.' : 'QR contains the private .conf for compatible scanners. Scanner compatibility is unverified; download .conf is recommended.';
      $('create-config-copy').textContent = labels.copy;
      $('create-config-download').textContent = labels.download;
    }
    const realResult = realCanary && wizard.step === 'result' && Boolean(wizard.result);
    $('create-real-result').hidden = !realResult;
    $('create-config-text').value = realResult ? wizard.result.configText : '';
    const canvas = $('create-qr');
    if (realResult && canvas.dataset.rendered !== 'true') {
      if (canvas.dataset.pending !== 'true') {
        canvas.dataset.pending = 'true';
        renderCreatedQr(wizard.result).finally(() => { delete canvas.dataset.pending; });
      }
    } else if (!realResult) {
      canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
      delete canvas.dataset.rendered;
    }
    $('preview-result-id').textContent = wizard.result ? (realCanary ? wizard.result.client.id : wizard.result.previewId) : '—';
    $('preview-result-name').textContent = wizard.result ? (realCanary ? wizard.result.client.name : wizard.result.name) : '—';
    $('preview-result-tags').textContent = wizard.result ? ((realCanary ? wizard.result.client.tags : wizard.result.tags).join(', ') || t('noTags')) : '—';
    $('preview-result-status').textContent = wizard.result ? (realCanary ? wizard.result.client.status : wizard.result.status) : 'DRY_RUN';
    $('preview-result-boundary').textContent = wizard.result ? (realCanary ? (state.locale === 'ru' ? 'Реальный peer создан · сохраните конфигурацию сейчас' : 'Real peer created · save configuration now') : wizard.result.boundary + ' · KEYS / CONFIG / QR NOT GENERATED') : t('previewNoPeerCreated');
  }

  function renderActionMenu() {
    const menu = $('client-actions-menu');
    const client = state.clients.find((item) => item.id === state.actionMenu.clientId) || null;
    const visible = state.actionMenu.open && Boolean(client);
    menu.hidden = !visible;
    menu.setAttribute('aria-hidden', String(!visible));
    if (!client) return;
    menu.dataset.clientId = client.id;
    for (const name of ['edit', 'config']) {
      const button = $(`client-action-${name}`);
      const disabledAction = realCanary && name === 'edit';
      button.disabled = disabledAction;
      button.setAttribute('aria-disabled', String(disabledAction));
      button.setAttribute('role', disabledAction ? 'presentation' : 'menuitem');
      button.tabIndex = disabledAction ? -1 : 0;
    }
    const disabled = client.status === 'DISABLED';
    $('client-action-disable').hidden = disabled;
    $('client-action-disable').setAttribute('role', disabled ? 'presentation' : 'menuitem');
    $('client-action-disable').tabIndex = disabled ? -1 : 0;
    $('client-action-enable').hidden = !disabled;
    $('client-action-enable').setAttribute('role', disabled ? 'menuitem' : 'presentation');
    $('client-action-enable').tabIndex = disabled ? 0 : -1;
  }

  function positionActionMenu(clientId) {
    const toggle = Array.from(document.querySelectorAll('[data-action-menu-toggle]')).find((node) => node.dataset.actionMenuToggle === clientId);
    const menu = $('client-actions-menu');
    if (!toggle || menu.hidden) return;
    const rect = toggle.getBoundingClientRect();
    const menuRect = menu.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.right - menuRect.width, window.innerWidth - menuRect.width - 8));
    const below = rect.bottom + 6;
    const top = below + menuRect.height <= window.innerHeight - 8 ? below : Math.max(8, rect.top - menuRect.height - 6);
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
  }

  function focusClientAction(clientId) {
    const toggle = Array.from(document.querySelectorAll('[data-action-menu-toggle]')).find((node) => node.dataset.actionMenuToggle === clientId);
    if (toggle) {
      toggle.focus();
      return;
    }
    $('client-search')?.focus();
  }

  function openActionMenu(clientId) {
    if (!state.clients.some((client) => client.id === clientId)) return;
    if (state.actionMenu.open && state.actionMenu.clientId === clientId) {
      closeActionMenu({ restoreFocus: true });
      return;
    }
    state.actionMenu = { open: true, clientId };
    render();
    positionActionMenu(clientId);
    const first = $('client-actions-menu').querySelector('[role="menuitem"]:not([hidden])');
    if (first) first.focus();
  }

  function closeActionMenu({ restoreFocus = false } = {}) {
    const clientId = state.actionMenu.clientId;
    state.actionMenu = { open: false, clientId: null };
    render();
    if (restoreFocus && clientId) focusClientAction(clientId);
  }

  function activeDialog() {
    return document.querySelector('.modal-backdrop:not([hidden]) [role="dialog"]');
  }

  function dialogFocusables(dialog) {
    return Array.from(dialog?.querySelectorAll('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])') || []).filter((node) => !node.hidden);
  }

  function recordAuditAction(action, target, result = 'OK', reasonRu = 'Mock frontend action выполнен.', reasonEn = 'Mock frontend action completed.') {
    const now = new Date().toISOString();
    appendAuditEvent({
      id: `event-runtime-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      timestamp: now,
      actor: 'OPERATOR',
      action,
      target,
      result,
      correlationId: `corr-runtime-${Date.now()}`,
      reasonRu,
      reasonEn
    });
    addActivity(action, target, result);
  }

  function renderEditClient() {
    const edit = state.editClient;
    const modal = $('edit-client-modal');
    modal.hidden = !edit.open;
    modal.setAttribute('aria-hidden', String(!edit.open));
    $('edit-name').value = edit.name;
    $('edit-notes').value = edit.notes;
    $('edit-tags').value = edit.tagsInput;
    $('edit-expiration').value = edit.expiration;
    $('edit-form-error').hidden = !edit.error;
    $('edit-form-error').textContent = edit.error ? t(edit.error) : '';
    $('edit-save').disabled = edit.submitting;
  }

  function renderDeleteClient() {
    const deletion = state.deleteClient;
    const modal = $('delete-client-modal');
    const client = state.clients.find((item) => item.id === deletion.clientId) || null;
    modal.hidden = !deletion.open || !client;
    modal.setAttribute('aria-hidden', String(!deletion.open || !client));
    if (!client) return;
    $('delete-client-name').textContent = client.name;
    $('delete-confirm').disabled = deletion.submitting;
    if (realCanary) {
      $('delete-dialog-copy').textContent = state.locale === 'ru' ? 'Peer будет безвозвратно удалён из конфигурации awg-canary0.' : 'The peer will be permanently removed from awg-canary0.';
      document.querySelector('[data-i18n="deleteBoundary"]').textContent = state.locale === 'ru' ? 'Удаление применяется на сервере после перезапуска.' : 'Deletion is applied on the server after restart.';
      $('delete-confirm').textContent = state.locale === 'ru' ? 'Удалить peer' : 'Delete peer';
    }
  }

  function renderConfigPreview() {
    const config = state.configPreview;
    if (realCanary) {
      const ru = state.locale === 'ru';
      $('config-preview-title').textContent = ru ? 'Конфигурация клиента' : 'Client configuration';
      $('config-preview-copy-text').textContent = ru ? 'Приватная конфигурация. Скачивайте и показывайте QR только на доверенном устройстве.' : 'Private configuration. Download and display the QR only on a trusted device.';
      $('config-preview-download').textContent = ru ? 'Скачать .conf' : 'Download .conf';
    }
    const modal = $('config-preview-modal');
    modal.hidden = !config.open;
    modal.setAttribute('aria-hidden', String(!config.open));
    const result = config.result;
    $('config-preview-tab-qr').setAttribute('aria-selected', String(config.tab === 'qr'));
    $('config-preview-tab-config').setAttribute('aria-selected', String(config.tab === 'config'));
    $('config-preview-tab-qr').classList.toggle('is-active', config.tab === 'qr');
    $('config-preview-tab-config').classList.toggle('is-active', config.tab === 'config');
    $('config-preview-qr-panel').hidden = !config.open || config.tab !== 'qr';
    $('config-preview-config-panel').hidden = !config.open || config.tab !== 'config';
    $('config-preview-copy').disabled = config.loading || !result;
    $('config-preview-download').disabled = config.loading || !result;
    if (!result) {
      $('config-preview-name').textContent = '—';
      $('config-preview-expiration').textContent = '—';
      $('config-preview-status').textContent = '—';
      $('config-preview-qr').setAttribute('aria-label', t('configQrTab'));
      $('config-preview-qr').replaceChildren();
      $('config-preview-qr-payload').textContent = '—';
      $('config-preview-text').textContent = '# MOCK CONFIGURATION';
      return;
    }
    $('config-preview-name').textContent = result.clientName;
    $('config-preview-expiration').textContent = result.expiration ? formatDate(result.expiration) : '—';
    $('config-preview-status').textContent = result.status;
    $('config-preview-qr').setAttribute('aria-label', `${t('configQrTab')}: ${result.clientName} · ${result.status}`);
    if (realCanary) {
      const qr = document.createElement('img');
      qr.src = result.qrDataUri;
      qr.alt = state.locale === 'ru' ? 'QR конфигурации клиента' : 'Client configuration QR';
      qr.width = 220;
      qr.height = 220;
      $('config-preview-qr').replaceChildren(qr);
      $('config-preview-qr-payload').textContent = state.locale === 'ru' ? 'QR содержит приватную конфигурацию' : 'QR contains private configuration';
    } else {
      $('config-preview-qr-payload').textContent = result.qrPayload;
    }
    $('config-preview-text').textContent = result.configText;
  }

  function parseTagsInput(value) {
    const tagsInput = String(value || '').trim();
    const rawTags = tagsInput ? tagsInput.split(',').map((tag) => tag.trim()) : [];
    return { tagsInput, rawTags, tags: rawTags.filter(Boolean) };
  }

  function resetEditClient() {
    state.editClient = { open: false, clientId: null, name: '', notes: '', tagsInput: '', tags: [], expiration: '', submitting: false, error: '' };
  }

  function openEditClient(id) {
    const client = state.clients.find((item) => item.id === id);
    if (!client) return;
    state.actionMenu = { open: false, clientId: null };
    state.editClient = { open: true, clientId: id, name: client.name, notes: client.notes || '', tagsInput: (client.tags || []).join(', '), tags: [...(client.tags || [])], expiration: client.expiration || '', submitting: false, error: '' };
    render();
    window.setTimeout(() => $('edit-name').focus(), 0);
  }

  function closeEditClient({ restoreFocus = true } = {}) {
    const id = state.editClient.clientId;
    resetEditClient();
    render();
    if (restoreFocus && id) focusClientAction(id);
  }

  function collectEditMetadata() {
    const name = $('edit-name').value.trim();
    const notes = $('edit-notes').value.trim();
    const parsedTags = parseTagsInput($('edit-tags').value);
    const expiration = $('edit-expiration').value;
    state.editClient.name = name;
    state.editClient.notes = notes;
    state.editClient.tagsInput = parsedTags.tagsInput;
    state.editClient.tags = parsedTags.tags;
    state.editClient.expiration = expiration;
    state.editClient.error = '';
    if (!PREVIEW_NAME_PATTERN.test(name)) {
      state.editClient.error = 'editNameInvalid';
      return false;
    }
    if (notes.length > MAX_NOTES_LENGTH) {
      state.editClient.error = 'editNotesInvalid';
      return false;
    }
    if (parsedTags.rawTags.some((tag) => !tag) || parsedTags.tags.some((tag) => !PREVIEW_TAG_PATTERN.test(tag))) {
      state.editClient.error = 'editTagsInvalid';
      return false;
    }
    if (parsedTags.tags.length > 5) {
      state.editClient.error = 'editTagsTooMany';
      return false;
    }
    if (!isValidExpiration(expiration)) {
      state.editClient.error = 'editExpirationInvalid';
      return false;
    }
    return true;
  }

  async function submitEditClient() {
    if (state.editClient.submitting) return;
    if (!collectEditMetadata()) {
      render();
      $('edit-name').focus();
      return;
    }
    state.editClient.submitting = true;
    render();
    const id = state.editClient.clientId;
    try {
      if (typeof adapter.updateClient !== 'function') throw new Error('backend_stub');
      const updated = normalizeUpdatedClient(await adapter.updateClient(id, { name: state.editClient.name, notes: state.editClient.notes, tags: state.editClient.tags, expiration: state.editClient.expiration }), id);
      state.clients = state.clients.map((client) => client.id === id ? updated : client);
      state.selectedClientId = id;
      state.dossierOpen = true;
      recordAuditAction('CLIENT_UPDATED', updated.name, 'OK', 'Метаданные клиента обновлены в mock state.', 'Client metadata updated in mock state.');
      resetEditClient();
      render();
      showToast(t('clientUpdated'), 'success');
      focusClientAction(id);
    } catch (_error) {
      state.editClient.error = 'editAdapterError';
      state.editClient.submitting = false;
      render();
    }
  }

  function openStatusClient(id, nextStatus) {
    const client = state.clients.find((item) => item.id === id);
    if (!client || state.statusClient.submitting) return;
    state.actionMenu = { open: false, clientId: null };
    state.statusClient = { open: false, clientId: id, nextStatus, submitting: false };
    submitStatusClient();
  }

  async function submitStatusClient() {
    if (state.statusClient.submitting) return;
    state.statusClient.submitting = true;
    render();
    const id = state.statusClient.clientId;
    const nextStatus = state.statusClient.nextStatus;
    const action = nextStatus === 'ONLINE' ? 'CLIENT_ENABLED' : 'CLIENT_DISABLED';
    try {
      const method = nextStatus === 'ONLINE' ? 'enableClient' : 'disableClient';
      if (typeof adapter[method] !== 'function') throw new Error('backend_stub');
      const updated = normalizeUpdatedClient(await adapter[method](id), id);
      state.clients = state.clients.map((client) => client.id === id ? updated : client);
      state.selectedClientId = id;
      state.dossierOpen = true;
      recordAuditAction(action, updated.name, 'OK', realCanary ? 'Изменение применено на awg-canary0.' : nextStatus === 'ONLINE' ? 'Клиент включён в mock state.' : 'Клиент отключён в mock state.', realCanary ? 'Change applied on awg-canary0.' : nextStatus === 'ONLINE' ? 'Client enabled in mock state.' : 'Client disabled in mock state.');
      state.statusClient = { open: false, clientId: null, nextStatus: 'ONLINE', submitting: false };
      render();
      showToast(realCanary ? (state.locale === 'ru' ? 'Изменение peer сохранено на сервере' : 'Peer change saved on server') : t(nextStatus === 'ONLINE' ? 'clientEnabled' : 'clientDisabled'), 'success');
      focusClientAction(id);
    } catch (_error) {
      state.statusClient = { open: false, clientId: null, nextStatus: 'ONLINE', submitting: false };
      render();
      showToast(t('statusAdapterError'), 'error');
      focusClientAction(id);
    }
  }

  function openDeleteClient(id) {
    const client = state.clients.find((item) => item.id === id);
    if (!client) return;
    state.actionMenu = { open: false, clientId: null };
    state.deleteClient = { open: true, clientId: id, submitting: false };
    render();
    window.setTimeout(() => $('delete-confirm').focus(), 0);
  }

  function closeDeleteClient({ restoreFocus = true } = {}) {
    const id = state.deleteClient.clientId;
    state.deleteClient = { open: false, clientId: null, submitting: false };
    render();
    if (restoreFocus && id) focusClientAction(id);
  }

  async function submitDeleteClient() {
    if (state.deleteClient.submitting) return;
    state.deleteClient.submitting = true;
    render();
    const id = state.deleteClient.clientId;
    try {
      if (typeof adapter.deleteClient !== 'function') throw new Error('backend_stub');
      normalizeDeleteResult(await adapter.deleteClient(id), id);
      const client = state.clients.find((item) => item.id === id);
      state.clients = state.clients.filter((item) => item.id !== id);
      if (state.selectedClientId === id) {
        state.selectedClientId = null;
        state.dossierOpen = false;
      }
      recordAuditAction('CLIENT_DELETED', client?.name || id, 'OK', realCanary ? 'Peer удалён из awg-canary0.' : 'Client record удалён только из mock state.', realCanary ? 'Peer removed from awg-canary0.' : 'Client record deleted only from mock state.');
      state.deleteClient = { open: false, clientId: null, submitting: false };
      render();
      showToast(realCanary ? (state.locale === 'ru' ? 'Peer удалён на сервере' : 'Peer deleted on server') : t('clientDeleted'), 'success');
      focusClientAction(state.selectedClientId || '');
    } catch (_error) {
      state.deleteClient.submitting = false;
      render();
      showToast(t('deleteAdapterError'), 'error');
    }
  }

  async function openConfigurationPreview(id) {
    const client = state.clients.find((item) => item.id === id);
    if (!client) return;
    const requestToken = {};
    activeConfigPreviewRequest = requestToken;
    const isCurrentRequest = () => activeConfigPreviewRequest === requestToken &&
      state.configPreview.open && state.configPreview.clientId === id;
    state.actionMenu = { open: false, clientId: null };
    state.configPreview = { open: true, clientId: id, tab: 'qr', loading: true, error: '', result: null };
    render();
    window.setTimeout(() => $('config-preview-tab-qr').focus(), 0);
    try {
      if (typeof adapter.generateConfigurationPreview !== 'function') throw new Error('backend_stub');
      const preview = await adapter.generateConfigurationPreview(id);
      if (!isCurrentRequest()) return;
      const currentClient = state.clients.find((item) => item.id === id);
      if (realCanary) {
        const result = normalizeCreatedClient({ ...preview, oneTime: false }, currentClient.name, currentClient.tags);
        if (result.client.id !== id) throw new Error('malformed_configuration_result');
        state.configPreview.result = { clientId: id, clientName: currentClient.name,
          expiration: currentClient.expiration || '', status: currentClient.status,
          configText: result.configText, qrDataUri: result.qrDataUri };
      } else {
        state.configPreview.result = normalizeConfigurationPreview(preview, currentClient);
        recordAuditAction('CONFIG_PREVIEWED', client.name, 'DRY_RUN', 'Configuration preview содержит только mock data.', 'Configuration preview contains mock data only.');
      }
      showToast(t('configDownloadReady'), 'success');
    } catch (_error) {
      if (!isCurrentRequest()) return;
      state.configPreview.error = 'configAdapterError';
      showToast(t('configAdapterError'), 'error');
    } finally {
      if (isCurrentRequest()) {
        state.configPreview.loading = false;
        render();
      }
    }
  }

  function closeConfigurationPreview({ restoreFocus = true } = {}) {
    const id = state.configPreview.clientId;
    activeConfigPreviewRequest = null;
    state.configPreview = { open: false, clientId: null, tab: 'qr', loading: false, error: '', result: null };
    render();
    if (restoreFocus && id) focusClientAction(id);
  }

  function setConfigurationTab(tab) {
    state.configPreview.tab = tab === 'config' ? 'config' : 'qr';
    render();
    $(`config-preview-tab-${state.configPreview.tab}`).focus();
  }

  async function copyConfiguration() {
    const result = state.configPreview.result;
    if (!result) return;
    let copied = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(result.configText);
        copied = true;
      }
    } catch (_error) {
      copied = false;
    }
    if (!copied) {
      const helper = document.createElement('textarea');
      helper.value = result.configText;
      helper.setAttribute('readonly', '');
      helper.style.position = 'fixed';
      helper.style.opacity = '0';
      document.body.appendChild(helper);
      helper.select();
      copied = document.execCommand('copy');
      helper.remove();
    }
    showToast(copied ? t('configCopySuccess') : t('configAdapterError'), copied ? 'success' : 'error');
  }

  function downloadMockConfiguration() {
    const result = state.configPreview.result;
    if (!result) return;
    const blob = new Blob([result.configText], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = realCanary ? `awg-cita-${result.clientId}.conf` : `awg-cita-mock-${result.clientId}.conf`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    showToast(t('configDownloadReady'), 'success');
  }

  function resetCreatePreview() {
    state.createPreview = {
      open: false,
      step: 'form',
      name: '',
      tagsInput: '',
      tags: [],
      submitting: false,
      error: '',
      result: null
    };
  }

  function openCreatePreview() {
    resetCreatePreview();
    state.createPreview.open = true;
    render();
    window.setTimeout(() => $('preview-name').focus(), 0);
  }

  function closeCreatePreview() {
    if (state.createPreview.submitting) return;
    resetCreatePreview();
    render();
    $('add-client-button').focus();
  }

  function collectCreatePreviewMetadata() {
    const name = $('preview-name').value.trim();
    const tagsInput = $('preview-tags').value.trim();
    const rawTags = tagsInput ? tagsInput.split(',').map((tag) => tag.trim()) : [];
    const tags = rawTags.filter(Boolean);
    state.createPreview.name = name;
    state.createPreview.tagsInput = tagsInput;
    state.createPreview.tags = tags;
    state.createPreview.error = '';
    if (!name) {
      state.createPreview.error = 'previewNameRequired';
      return false;
    }
    if (!PREVIEW_NAME_PATTERN.test(name)) {
      state.createPreview.error = 'previewNameInvalid';
      return false;
    }
    if (rawTags.some((tag) => !tag) || tags.some((tag) => !PREVIEW_TAG_PATTERN.test(tag))) {
      state.createPreview.error = 'previewTagsInvalid';
      return false;
    }
    if (tags.length > 5) {
      state.createPreview.error = 'previewTagsTooMany';
      return false;
    }
    return true;
  }

  async function submitCreatePreview() {
    if (state.createPreview.step !== 'form') return;
    if (state.createPreview.submitting) {
      render();
      return;
    }
    if (!collectCreatePreviewMetadata()) {
      render();
      $('preview-name').focus();
      return;
    }
    state.createPreview.submitting = true;
    state.createPreview.error = '';
    render();
    try {
      if (realCanary) {
        const attempt = { nonce: crypto.randomUUID(), name: state.createPreview.name,
          tags: state.createPreview.tags.slice() };
        const result = normalizeCreatedClient(await adapter.createClient({
          name: attempt.name,
          tags: attempt.tags,
          idempotencyKey: attempt.nonce,
          acknowledged: true
        }), attempt.name, attempt.tags);
        state.createPreview.result = result;
        state.createPreview.step = 'result';
        // Read back only public records; never feed private configuration to activity/audit hooks.
        try {
          state.clients = normalizeClients(await adapter.listClients());
          state.lastRefresh = new Date().toISOString();
        } catch (_readError) {
          showToast(state.locale === 'ru' ? 'Peer создан; обновление списка не удалось. Проверьте список вручную.' : 'Peer created; list refresh failed. Check the list manually.', 'error');
        }
      } else {
      if (typeof adapter.previewCreateClient !== 'function') throw new Error('backend_stub');
      const result = normalizePreviewResult(await adapter.previewCreateClient({
        name: state.createPreview.name,
        tags: state.createPreview.tags,
        acknowledged: true
      }));
      state.createPreview.result = result;
      state.createPreview.step = 'result';
      appendAuditEvent({
        id: `event-preview-${Date.now()}`,
        timestamp: new Date().toISOString(),
        actor: 'OPERATOR',
        action: 'CLIENT_PREVIEWED',
        target: result.name,
        result: 'DRY_RUN',
        correlationId: `corr-preview-${Date.now()}`,
        reasonRu: 'Preview выполнен без создания peer; lifecycle не выполнялся.',
        reasonEn: 'Preview completed without creating a peer; no lifecycle operation ran.'
      });
      addActivity('CLIENT_PREVIEWED', result.name, 'DRY_RUN');
      showToast(t('previewResultHeading'), 'success');
      }
    } catch (_error) {
      state.createPreview.error = realCanary ? 'realCreateError' : 'previewAdapterError';
      if (realCanary) {
        try { state.clients = normalizeClients(await adapter.listClients()); } catch (_readError) { /* Create stays available. */ }
      }
    } finally {
      state.createPreview.submitting = false;
      render();
    }
  }

  async function copyCreatedConfiguration() {
    const text = state.createPreview.result?.configText;
    if (!realCanary || !text || state.createPreview.step !== 'result') return;
    try {
      await navigator.clipboard.writeText(text);
      showToast(state.locale === 'ru' ? 'Конфигурация скопирована' : 'Configuration copied', 'success');
    } catch (_error) {
      showToast(state.locale === 'ru' ? 'Копирование не удалось; скачайте .conf' : 'Copy failed; download .conf instead', 'error');
    }
  }

  function downloadCreatedConfiguration() {
    const result = state.createPreview.result;
    if (!realCanary || !result || state.createPreview.step !== 'result') return;
    const url = URL.createObjectURL(new Blob([result.configText], { type: 'text/plain;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `awg-cita-${result.client.id}.conf`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  function render() {
    applyTranslations();
    if (realCanary) {
      const ru = state.locale === 'ru';
      document.querySelector('.rail-status strong').textContent = 'AWG-CITA / CANARY';
      document.querySelector('.rail-status small').textContent = ru ? 'Реальные действия с peer' : 'Real peer actions';
      $('mutation-boundary').textContent = ru ? 'Create / Disable / Enable / Delete применяются к awg-canary0. Конфигурация и QR доступны в меню клиента.' : 'Create / Disable / Enable / Delete apply to awg-canary0. Configuration and QR are available in the client menu.';
      document.querySelector('[data-i18n="trafficDescription"]').textContent = ru ? 'RX + TX по AWG read-back' : 'RX + TX from AWG read-back';
      document.querySelector('[data-i18n="deleteEyebrow"]').textContent = 'DESTRUCTIVE ACTION / AWG CANARY';
    }
    renderNavigation();
    renderConnection();
    renderOverview();
    const visibleClients = getVisibleClients();
    reconcileSelection(visibleClients);
    renderClients(visibleClients);
    renderDossier();
    renderJournal();
    renderGlobalError();
    renderToasts();
    renderActionMenu();
    renderEditClient();
    renderDeleteClient();
    renderConfigPreview();
    renderCreatePreview();
  }

  function viewFromLocation() {
    const view = window.location.hash.slice(1).split('?')[0];
    return ['clients', 'journal'].includes(view) ? view : 'overview';
  }

  function navigate(view, { fromHistory = false } = {}) {
    const nextView = ['clients', 'journal'].includes(view) ? view : 'overview';
    if (!fromHistory && window.location.hash !== `#${nextView}`) window.history.pushState({}, '', `#${nextView}`);
    state.currentView = nextView;
    if (nextView === 'clients') state.hasVisitedClients = true;
    render();
  }

  async function loadClients() {
    state.loading = true;
    state.error = '';
    render();
    try {
      const [clientResult, observabilityResult] = await Promise.all([
        adapter.listClients(),
        typeof adapter.listObservability === 'function' ? adapter.listObservability() : clone(observabilityFixtures)
      ]);
      state.clients = normalizeClients(clientResult);
      const observability = normalizeObservability(observabilityResult);
      state.observabilitySchemaVersion = observability.schemaVersion;
      state.retentionDays = observability.retentionDays;
      state.statusHistory = observability.statusHistory;
      state.auditEvents = observability.auditEvents;
      state.alerts = observability.alerts;
      state.refreshFailures = 0;
      state.lastRefresh = new Date().toISOString();
      addActivity(t(realCanary ? 'refreshed' : 'loadedFixtures'), `${state.clients.length} ${t('records')}`);
    } catch (_error) {
      state.error = t('malformedResult');
      state.clients = [];
      state.statusHistory = [];
      state.auditEvents = [];
      state.alerts = [];
    } finally {
      state.loading = false;
      render();
    }
  }

  async function refreshStatus() {
    if (state.refreshing) return;
    state.refreshing = true;
    state.error = '';
    render();
    try {
      state.clients = normalizeClients(await adapter.refreshStatus());
      const now = new Date().toISOString();
      const onlineCount = state.clients.filter((client) => client.status === 'ONLINE').length;
      const attentionCount = state.clients.filter((client) => ['STALE', 'NEVER', 'DISABLED'].includes(client.status) || client.warning).length;
      state.statusHistory = [{ id: `snapshot-runtime-${Date.now()}`, checkedAt: now, state: 'OK', peerCount: state.clients.length, onlineCount, attentionCount, rxBytes: state.clients.reduce((sum, client) => sum + (Number(client.rxBytes) || 0), 0), txBytes: state.clients.reduce((sum, client) => sum + (Number(client.txBytes) || 0), 0), reasonRu: realCanary ? 'Обновление из AWG read-back.' : 'Обновление выполнено из mock adapter.', reasonEn: realCanary ? 'Refreshed from AWG read-back.' : 'Refresh completed by the mock adapter.' }, ...state.statusHistory].slice(0, 60);
      state.auditEvents = [{ id: `event-runtime-${Date.now()}`, timestamp: now, actor: 'OPERATOR', action: 'STATUS_REFRESHED', target: 'AWG node', result: 'OK', correlationId: `corr-runtime-${Date.now()}`, reasonRu: 'Оператор запросил обновление состояния.', reasonEn: 'Operator requested a status refresh.' }, ...state.auditEvents].slice(0, 120);
      state.refreshFailures = 0;
      state.lastRefresh = new Date().toISOString();
      addActivity(t('refreshed'), `${state.clients.length} ${t('records')}`);
      showToast(t('refreshSuccess'), 'success');
    } catch (_error) {
      state.refreshFailures += 1;
      const now = new Date().toISOString();
      state.auditEvents = [{ id: `event-runtime-error-${Date.now()}`, timestamp: now, actor: 'SYSTEM', action: 'STATUS_REFRESH_FAILED', target: 'AWG node', result: 'ERROR', correlationId: `corr-runtime-error-${Date.now()}`, reasonRu: realCanary ? 'AWG read-back вернул ошибку.' : 'Mock adapter вернул ошибку обновления.', reasonEn: realCanary ? 'AWG read-back failed.' : 'The mock adapter returned a refresh error.' }, ...state.auditEvents].slice(0, 120);
      state.error = t('refreshError');
      showToast(t('refreshError'), 'error');
    } finally {
      state.refreshing = false;
      render();
    }
  }

  function selectClient(id) {
    if (!state.clients.some((client) => client.id === id)) return;
    state.actionMenu = { open: false, clientId: null };
    state.selectedClientId = id;
    state.dossierOpen = true;
    render();
  }

  function clearFilters() {
    state.searchQuery = '';
    state.statusFilters.clear();
    render();
  }

  function toggleStatusFilter(status) {
    if (state.statusFilters.has(status)) state.statusFilters.delete(status);
    else state.statusFilters.add(status);
    render();
  }

  function toggleSort(key) {
    if (state.sort.key === key) state.sort.direction = state.sort.direction === 'asc' ? 'desc' : 'asc';
    else state.sort = { key, direction: 'asc' };
    render();
  }

  function closeLanguageMenu() {
    $('language-list').hidden = true;
    $('language-toggle').setAttribute('aria-expanded', 'false');
  }

  document.addEventListener('click', (event) => {
    const viewButton = event.target.closest('[data-view]');
    if (viewButton) {
      navigate(viewButton.dataset.view);
      return;
    }
    const languageToggle = event.target.closest('#language-toggle');
    if (languageToggle) {
      const list = $('language-list');
      list.hidden = !list.hidden;
      languageToggle.setAttribute('aria-expanded', String(!list.hidden));
      return;
    }
    const languageButton = event.target.closest('[data-lang]');
    if (languageButton) {
      const previousLocale = state.locale;
      state.locale = languageButton.dataset.lang === 'en' ? 'en' : 'ru';
      closeLanguageMenu();
      if (previousLocale !== state.locale) recordAuditAction('LOCALE_CHANGED', state.locale.toUpperCase(), 'OK', 'Язык интерфейса изменён оператором.', 'Interface language changed by the operator.');
      render();
      return;
    }
    if (!event.target.closest('.language-menu')) closeLanguageMenu();

    const actionToggle = event.target.closest('[data-action-menu-toggle]');
    if (actionToggle) {
      openActionMenu(actionToggle.dataset.actionMenuToggle);
      return;
    }
    const actionItem = event.target.closest('[data-client-action]');
    if (actionItem) {
      const clientId = $('client-actions-menu').dataset.clientId;
      const action = actionItem.dataset.clientAction;
      if (action === 'open') selectClient(clientId);
      else if (action === 'edit') openEditClient(clientId);
      else if (action === 'config') openConfigurationPreview(clientId);
      else if (action === 'disable') openStatusClient(clientId, 'DISABLED');
      else if (action === 'enable') openStatusClient(clientId, 'ONLINE');
      else if (action === 'delete') openDeleteClient(clientId);
      return;
    }
    if (state.actionMenu.open && !event.target.closest('#client-actions-menu')) {
      closeActionMenu();
    }
    if (event.target.matches('#edit-client-modal')) {
      closeEditClient();
      return;
    }
    if (event.target.closest('#edit-close') || event.target.closest('#edit-cancel')) {
      closeEditClient();
      return;
    }
    if (event.target.closest('#edit-save')) {
      submitEditClient();
      return;
    }
    if (event.target.matches('#delete-client-modal')) {
      closeDeleteClient();
      return;
    }
    if (event.target.closest('#delete-close') || event.target.closest('#delete-cancel')) {
      closeDeleteClient();
      return;
    }
    if (event.target.closest('#delete-confirm')) {
      submitDeleteClient();
      return;
    }
    if (event.target.matches('#config-preview-modal')) {
      closeConfigurationPreview();
      return;
    }
    if (event.target.closest('#config-preview-close') || event.target.closest('#config-preview-close-action')) {
      closeConfigurationPreview();
      return;
    }
    const configTab = event.target.closest('[data-config-tab]');
    if (configTab) {
      setConfigurationTab(configTab.dataset.configTab);
      return;
    }
    if (event.target.closest('#config-preview-copy')) {
      copyConfiguration();
      return;
    }
    if (event.target.closest('#config-preview-download')) {
      downloadMockConfiguration();
      return;
    }
    if (event.target.closest('#dossier-config-button')) {
      if (state.selectedClientId) openConfigurationPreview(state.selectedClientId);
      return;
    }
    if (event.target.closest('#create-config-copy')) {
      copyCreatedConfiguration();
      return;
    }
    if (event.target.closest('#create-config-download')) {
      downloadCreatedConfiguration();
      return;
    }
    if (event.target.matches('#create-preview-modal')) {
      closeCreatePreview();
      return;
    }
    if (event.target.closest('#add-client-button')) {
      openCreatePreview();
      return;
    }
    if (event.target.closest('#preview-close') || event.target.closest('#preview-cancel') || event.target.closest('#preview-done')) {
      closeCreatePreview();
      return;
    }
    if (event.target.closest('#preview-submit')) {
      submitCreatePreview();
      return;
    }
    const statusButton = event.target.closest('[data-status-filter]');
    if (statusButton) {
      toggleStatusFilter(statusButton.dataset.statusFilter);
      return;
    }
    const sortButton = event.target.closest('[data-sort-key]');
    if (sortButton) {
      toggleSort(sortButton.dataset.sortKey);
      return;
    }
    const rowButton = event.target.closest('[data-select-client]');
    if (rowButton) {
      selectClient(rowButton.dataset.selectClient);
      return;
    }
    const row = event.target.closest('.client-row');
    if (row) {
      selectClient(row.dataset.clientId);
      return;
    }
    if (event.target.closest('#refresh-button')) {
      refreshStatus();
      return;
    }
    if (event.target.closest('#export-json')) {
      downloadEvidence('json');
      return;
    }
    if (event.target.closest('#export-csv')) {
      downloadEvidence('csv');
      return;
    }
    if (event.target.closest('#clear-search')) {
      state.searchQuery = '';
      render();
      $('client-search').focus();
      return;
    }
    if (event.target.closest('#clear-filters') || event.target.closest('#reset-empty')) {
      clearFilters();
      return;
    }
    if (event.target.closest('#dossier-close')) {
      if (window.matchMedia('(max-width: 780px)').matches) state.dossierOpen = false;
      else state.selectedClientId = null;
      render();
    }
  });

  document.addEventListener('input', (event) => {
    if (event.target.matches('#client-search')) {
      state.searchQuery = event.target.value;
      render();
      $('client-search').focus();
      return;
    }
    if (event.target.matches('#journal-search')) {
      state.journalSearch = event.target.value;
      render();
      $('journal-search').focus();
      return;
    }
    if (event.target.matches('#preview-name')) {
      state.createPreview.name = event.target.value;
      state.createPreview.error = '';
      $('preview-form-error').hidden = true;
      return;
    }
    if (event.target.matches('#preview-tags')) {
      state.createPreview.tagsInput = event.target.value;
      state.createPreview.error = '';
      $('preview-form-error').hidden = true;
      return;
    }
    if (event.target.matches('#edit-name, #edit-notes, #edit-tags, #edit-expiration')) {
      state.editClient.error = '';
      $('edit-form-error').hidden = true;
    }
  });

  document.addEventListener('change', (event) => {
    if (event.target.matches('#journal-result-filter')) {
      state.journalResultFilter = event.target.value;
      render();
      return;
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Tab') {
      const dialog = activeDialog();
      if (dialog) {
        const focusables = dialogFocusables(dialog);
        if (focusables.length) {
          const first = focusables[0];
          const last = focusables[focusables.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }
        return;
      }
    }
    if (state.actionMenu.open && event.target.closest('#client-actions-menu')) {
      const items = Array.from($('client-actions-menu').querySelectorAll('[role="menuitem"]:not([hidden])'));
      const index = items.indexOf(event.target.closest('[role="menuitem"]'));
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (items.length) items[(index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus();
        return;
      }
      if (event.key === 'Home' || event.key === 'End') {
        event.preventDefault();
        if (items.length) items[event.key === 'Home' ? 0 : items.length - 1].focus();
        return;
      }
    }
    if (event.key === 'Escape') {
      closeLanguageMenu();
      if (state.createPreview.open) {
        event.preventDefault();
        closeCreatePreview();
        return;
      }
      if (state.editClient.open) {
        event.preventDefault();
        closeEditClient();
        return;
      }
      if (state.deleteClient.open) {
        event.preventDefault();
        closeDeleteClient();
        return;
      }
      if (state.configPreview.open) {
        event.preventDefault();
        closeConfigurationPreview();
        return;
      }
      if (state.actionMenu.open) {
        event.preventDefault();
        closeActionMenu({ restoreFocus: true });
        return;
      }
      if (window.matchMedia('(max-width: 780px)').matches) {
        state.dossierOpen = false;
        render();
      }
      return;
    }
    if ((event.key === 'Enter' || event.key === ' ') && event.target.matches('.client-row')) {
      event.preventDefault();
      selectClient(event.target.dataset.clientId);
    }
  });

  window.addEventListener('popstate', () => navigate(viewFromLocation(), { fromHistory: true }));
  window.addEventListener('resize', renderDossier);

  if (testMode) {
    window.__AWG_CITA_TEST_HOOKS__ = {
      state,
      adapter,
      getVisibleClients,
      getVisibleAuditEvents,
      normalizeClients,
      normalizeObservability,
      normalizePreviewResult,
      safeEvidencePayload,
      downloadEvidence,
      refreshStatus,
      selectClient,
      openCreatePreview,
      submitCreatePreview
    };
  }

  state.currentView = viewFromLocation();
  render();
  loadClients();
})();
