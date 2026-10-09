const Auth = require('/lib/xp/auth')

const STATUS_OPEN = 'open'
const DEPOSIT_RATE = 0.2

exports.deposit = function (total) {
  const deposit = total * DEPOSIT_RATE
  return Math.round(deposit)
}

exports.canPay = function (booking) {
  return booking.status === STATUS_OPEN && Auth.hasRole('role:system.admin')
}

exports.overdue = function (booking, now) {
  if (booking.dueDate < now) {
    return true
  }
  return false
}
