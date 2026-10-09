'use strict'

const Cron = require('/lib/cron')
const Task = require('/lib/xp/task')

exports.run = function () {
  const config = { miniCron: '0 6 * * *' }
  if (config.miniCron) {
    Cron.schedule({
      name: 'mini-cron-job',
      cron: config.miniCron,
      callback: function () {
        Task.executeFunction({
          description: 'MINI_SWEEP',
          func: function () {
            require('/lib/mini-booking').sweep()
          },
        })
      },
    })
  }
}
