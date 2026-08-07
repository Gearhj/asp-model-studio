import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import "../src/index.css";
import BureauCatalogAdmin from "../src/steps/BureauCatalogAdmin";


ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route
          path="/tests/bureauCatalogAdmin.isolated.entry.html"
          element={<BureauCatalogAdmin />}
        />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);

