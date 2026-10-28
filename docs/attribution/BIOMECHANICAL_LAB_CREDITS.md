# License and Attribution Notices: Biomechanical Cybernetic Lab

This project incorporates and adapts third-party 3D models and anatomical datasets. All assets are utilized strictly in accordance with their respective open licenses.

---

## 1. BodyParts3D Anatomical Models

* **Source:** BodyParts3D, Database Center for Life Science (DBCLS), Japan.
* **License:** Creative Commons Attribution 4.0 International (CC BY 4.0).
* **Reference URL:** `https://lifesciencedb.jp/bp3d/`
* **Attribution Notice:**
  > BodyParts3D, © The Database Center for Life Science licensed under CC Attribution 4.0 International.
* **Modifications:** Anatomical joint assemblies (articular cartilage, femoral head, tibial plateau) have been isolated, re-meshed, and optimized for real-time WebGL rendering within Three.js / React Three Fiber.

---

## 2. NVIDIA SimReady Assets

* **Source:** NVIDIA SimReady Central Library (`nvidia/simready-assets`).
* **License:** Creative Commons Attribution 4.0 International (CC BY 4.0).
* **Packaging Manifest:** `com.nvidia.simready.packaging.json`
* **Reference URL:** `https://huggingface.co/datasets/nvidia/simready-assets`
* **Attribution Notice:**
  > Simulation-Ready 3D Assets, © NVIDIA Corporation licensed under Creative Commons Attribution 4.0 International (CC-BY-4.0).
* **Modifications:** Franka Emika Research 3 robotic arm and medical diagnostic equipment assets were converted from OpenUSD (`.usd`/`.usdc`) to glTF/GLB with Draco mesh compression, baked metallic-roughness materials, and simplified kinematic collision primitives.

---

## 3. Clinical Data Disclaimer

Kinematic telemetry curves and joint coordinate arrays displayed in the interactive 3D viewport and Remotion/HyperFrames hero film are **demonstration data** authored for portfolio visualization. They do not constitute diagnostic medical evaluations, certified clinical instrumentation, or clinical outcome guarantees.
