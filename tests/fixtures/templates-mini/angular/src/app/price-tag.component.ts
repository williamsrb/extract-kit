import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-price-tag',
  templateUrl: './price-tag.component.html',
})
export class PriceTagComponent {
  @Input() price: number;
}
