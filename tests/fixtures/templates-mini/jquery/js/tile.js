$(document).on('click', '#buy', function () {
  if (parseFloat($('#price').val()) > 150) {
    $('#premium').show();
  }
});
