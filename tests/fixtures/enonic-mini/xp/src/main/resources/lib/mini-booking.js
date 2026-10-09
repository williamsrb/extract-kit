const Context = require('/lib/xp/context')

exports.sweep = function () {
  return Context.run({ principals: ['role:system.admin'], repository: 'com.example.mini' }, function () {
    return []
  })
}
