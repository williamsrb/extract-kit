import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-product-tile',
  templateUrl: './product-tile.component.html',
})
export class ProductTileComponent {
  @Input() price: number;
}
