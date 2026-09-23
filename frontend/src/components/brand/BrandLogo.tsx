import { brand } from '../../config/brand'
export function BrandLogo() { return <a className="brand" href="#" aria-label="AI-ANA — главная"><img src={brand.logo} alt={brand.alt} width={brand.width} height={brand.height}/><span>{brand.name}<small>События начинаются с людей</small></span></a> }
