import React from 'react';
import {createRoot} from 'react-dom/client';
import UnifiedApp from './UnifiedApp.jsx';
import './styles.css';
import './unified.css';

createRoot(document.getElementById('root')).render(
  <React.StrictMode><UnifiedApp /></React.StrictMode>
);
