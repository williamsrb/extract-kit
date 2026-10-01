import { Component, EventEmitter, Input, Output } from '@angular/core';

@Component({
  selector: 'app-product-card',
  templateUrl: './product-card.component.html',
})
export class ProductCardComponent {
  @Input() title: string;
  @Input() price: number;
  @Input() items: string[];
  @Output() buy = new EventEmitter<void>();
}
