import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { brand } from './config/brand'
import '@fontsource-variable/manrope'
import './styles/tokens.css'
import './styles/account.css'
const favicon = document.createElement('link'); favicon.rel = 'icon'; favicon.href = brand.favicon; document.head.append(favicon)
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>)
