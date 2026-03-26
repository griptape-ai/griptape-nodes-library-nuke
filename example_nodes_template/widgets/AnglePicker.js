/**
 * CameraControl - A 3D camera control component matching the Qwen Image Edit Angles interface
 * Uses THREE.js for 3D visualization
 */

export default function AnglePicker(container, props) {
  const { value, onChange, disabled, height } = props;

  // Calculate size
  const size = height && height > 0 ? Math.max(150, height - 60) : 200;

  // Create DOM structure
  container.innerHTML = `
    <div class="camera-control-container nodrag nowheel" style="
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding: 8px;
      background-color: #1a1a1a;
      border-radius: 6px;
      user-select: none;
      box-sizing: border-box;
      width: 100%;
    ">
      <div class="three-wrapper" style="
        width: 100%;
        height: ${size}px;
        position: relative;
        border-radius: 4px;
        overflow: hidden;
      ">
        <div class="legend" style="
          position: absolute;
          bottom: 8px;
          left: 8px;
          font-size: 9px;
          color: #888;
          display: flex;
          flex-direction: column;
          gap: 2px;
          z-index: 10;
          pointer-events: none;
        ">
          <span><span style="color: #00ff88;">●</span> Rotation (↔)</span>
          <span><span style="color: #ff69b4;">●</span> Vertical Tilt (↕)</span>
          <span><span style="color: #ffa500;">●</span> Distance</span>
        </div>
      </div>
      <div class="prompt-text" style="
        font-size: 11px;
        color: #aaa;
        text-align: center;
        padding: 4px 8px;
        background-color: #252525;
        border-radius: 4px;
        min-height: 18px;
      ">No camera movement</div>
      <div style="display: flex; justify-content: space-between; font-size: 10px; color: #888; gap: 8px; align-items: center;">
        <span>Rot: <span class="rotate-value" style="color: #00ff88;">0°</span></span>
        <span>Tilt: <span class="tilt-value" style="color: #ff69b4;">0.0</span></span>
        <span>Dist: <span class="dist-value" style="color: #ffa500;">0</span></span>
        <button class="reset-btn" style="
          padding: 2px 8px;
          font-size: 9px;
          background-color: #333;
          border: 1px solid #444;
          border-radius: 3px;
          color: #fff;
          cursor: ${disabled ? 'not-allowed' : 'pointer'};
          opacity: ${disabled ? 0.5 : 1};
        " ${disabled ? 'disabled' : ''}>Reset</button>
      </div>
    </div>
  `;

  const wrapper = container.querySelector('.three-wrapper');
  const promptText = container.querySelector('.prompt-text');
  const rotateValue = container.querySelector('.rotate-value');
  const tiltValue = container.querySelector('.tilt-value');
  const distValue = container.querySelector('.dist-value');
  const resetBtn = container.querySelector('.reset-btn');

  // State - internal values are negated from output values
  // Output: positive rotate = right, positive tilt = worm's eye
  // Internal: we negate to match the visual coordinate system
  let rotateDeg = -(value?.rotate_deg ?? 0);
  let moveForward = value?.move_forward ?? 0;
  let verticalTilt = -(value?.vertical_tilt ?? 0);

  // Load THREE.js dynamically
  const loadThree = () => {
    return new Promise((resolve, reject) => {
      if (window.THREE) {
        resolve(window.THREE);
        return;
      }
      const script = document.createElement('script');
      script.src = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js';
      script.onload = () => resolve(window.THREE);
      script.onerror = reject;
      document.head.appendChild(script);
    });
  };

  let scene, camera, renderer, rotationHandle, tiltHandle, distanceHandle, cameraModel;
  let isDragging = false;
  let dragTarget = null;
  let dragStartMouse = { x: 0, y: 0 };
  let dragStartValue = 0;
  let raycaster, mouse;
  let animationId;

  const CENTER = { x: 0, y: 0.75, z: 0 };
  const BASE_DISTANCE = 2.0;
  const ROTATION_RADIUS = 2.2;
  const TILT_RADIUS = 1.6;

  function buildPromptText(rot, fwd, tilt) {
    const parts = [];
    if (Math.abs(rot) >= 1) {
      const dir = rot > 0 ? 'right' : 'left';
      parts.push(`Rotate ${Math.abs(Math.round(rot))}° ${dir}`);
    }
    if (fwd > 5) {
      parts.push('Close-up');
    } else if (fwd >= 1) {
      parts.push('Move forward');
    }
    if (tilt <= -0.5) {
      parts.push("Bird's-eye");
    } else if (tilt >= 0.5) {
      parts.push("Worm's-eye");
    }
    return parts.length > 0 ? parts.join(' • ') : 'No camera movement';
  }

  function updateDisplay() {
    // Display shows the output values (negated from internal state)
    const outputRotate = -rotateDeg;
    const outputTilt = -verticalTilt;
    rotateValue.textContent = `${outputRotate.toFixed(0)}°`;
    tiltValue.textContent = outputTilt.toFixed(1);
    distValue.textContent = moveForward.toFixed(0);
    promptText.textContent = buildPromptText(outputRotate, moveForward, outputTilt);
  }

  function updatePositions() {
    if (!rotationHandle || !tiltHandle || !distanceHandle || !cameraModel) return;

    const THREE = window.THREE;
    const rotRad = THREE.MathUtils.degToRad(-rotateDeg);
    const tiltRad = THREE.MathUtils.degToRad(verticalTilt * 35);
    const dist = BASE_DISTANCE - (moveForward / 10) * 1.5;

    // Rotation handle position (on horizontal arc)
    rotationHandle.position.set(
      Math.sin(rotRad) * ROTATION_RADIUS,
      0.05,
      Math.cos(rotRad) * ROTATION_RADIUS
    );

    // Tilt handle position (on vertical arc on the side, YZ plane at X=-0.7)
    tiltHandle.position.set(
      -0.7,
      CENTER.y + Math.sin(tiltRad) * TILT_RADIUS,
      Math.cos(tiltRad) * TILT_RADIUS
    );

    // Camera/distance handle position
    const camX = Math.sin(rotRad) * dist;
    const camY = CENTER.y + Math.sin(tiltRad) * dist * 0.5;
    const camZ = Math.cos(rotRad) * dist;

    distanceHandle.position.set(camX, camY, camZ);
    cameraModel.position.set(camX, camY, camZ);
    cameraModel.lookAt(CENTER.x, CENTER.y, CENTER.z);
  }

  // Emit change to React - only called on drag end for smooth interaction
  // Output values are negated to match expected convention:
  // - rotate_deg: positive = rotate right, negative = rotate left
  // - vertical_tilt: positive = worm's eye (looking up), negative = bird's eye (looking down)
  function emitChange() {
    if (disabled || !onChange) return;
    onChange({
      rotate_deg: -rotateDeg,
      move_forward: moveForward,
      vertical_tilt: -verticalTilt
    });
  }

  async function initScene() {
    const THREE = await loadThree();

    // Scene
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1a1a1a);

    // Camera
    camera = new THREE.PerspectiveCamera(50, wrapper.clientWidth / wrapper.clientHeight, 0.1, 1000);
    camera.position.set(4, 3, 4);
    camera.lookAt(0, 0.75, 0);

    // Renderer
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(wrapper.clientWidth, wrapper.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    wrapper.insertBefore(renderer.domElement, wrapper.firstChild);

    // Lights
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const dirLight = new THREE.DirectionalLight(0xffffff, 0.6);
    dirLight.position.set(5, 10, 5);
    scene.add(dirLight);

    // Grid
    scene.add(new THREE.GridHelper(6, 12, 0x333333, 0x222222));

    // Center target (gray sphere)
    const centerGeo = new THREE.SphereGeometry(0.15, 16, 16);
    const centerMat = new THREE.MeshStandardMaterial({ color: 0x666666 });
    const centerSphere = new THREE.Mesh(centerGeo, centerMat);
    centerSphere.position.set(CENTER.x, CENTER.y, CENTER.z);
    scene.add(centerSphere);

    // Rotation arc (green) - positioned for -90 to 90 degree range (front half)
    const rotArcGeo = new THREE.TorusGeometry(ROTATION_RADIUS, 0.02, 8, 64, Math.PI);
    const rotArcMat = new THREE.MeshBasicMaterial({ color: 0x00ff88 });
    const rotArc = new THREE.Mesh(rotArcGeo, rotArcMat);
    rotArc.rotation.x = Math.PI / 2;   // Lay flat on XZ plane
    // No Z rotation - arc naturally spans front half (-90 to +90)
    rotArc.position.y = 0.05;
    scene.add(rotArc);

    // Tilt arc (pink) - spans -35° to +35° (70° total = 70 * PI/180 radians)
    const tiltArcAngle = THREE.MathUtils.degToRad(70);
    const tiltArcGeo = new THREE.TorusGeometry(TILT_RADIUS, 0.02, 8, 32, tiltArcAngle);
    const tiltArcMat = new THREE.MeshBasicMaterial({ color: 0xff69b4 });
    const tiltArc = new THREE.Mesh(tiltArcGeo, tiltArcMat);
    tiltArc.rotation.y = Math.PI / 2;
    // Center the arc at 0° (front), so it spans from -35° to +35°
    tiltArc.rotation.z = THREE.MathUtils.degToRad(180 - 35);  // Flip to front side
    tiltArc.position.set(-0.7, CENTER.y, 0);
    scene.add(tiltArc);

    // Rotation handle (green sphere)
    const handleGeo = new THREE.SphereGeometry(0.15, 16, 16);
    const rotHandleMat = new THREE.MeshStandardMaterial({
      color: 0x00ff88,
      emissive: 0x00ff88,
      emissiveIntensity: 0.3
    });
    rotationHandle = new THREE.Mesh(handleGeo, rotHandleMat);
    rotationHandle.userData.type = 'rotation';
    scene.add(rotationHandle);

    // Tilt handle (pink sphere)
    const tiltHandleMat = new THREE.MeshStandardMaterial({
      color: 0xff69b4,
      emissive: 0xff69b4,
      emissiveIntensity: 0.3
    });
    tiltHandle = new THREE.Mesh(handleGeo.clone(), tiltHandleMat);
    tiltHandle.userData.type = 'tilt';
    scene.add(tiltHandle);

    // Distance handle (orange sphere)
    const distHandleMat = new THREE.MeshStandardMaterial({
      color: 0xffa500,
      emissive: 0xffa500,
      emissiveIntensity: 0.3
    });
    distanceHandle = new THREE.Mesh(handleGeo.clone(), distHandleMat);
    distanceHandle.userData.type = 'distance';
    scene.add(distanceHandle);

    // Camera model (simple box)
    const camBodyGeo = new THREE.BoxGeometry(0.3, 0.2, 0.2);
    const camMat = new THREE.MeshStandardMaterial({ color: 0x6699cc });
    cameraModel = new THREE.Mesh(camBodyGeo, camMat);
    scene.add(cameraModel);

    // Distance line
    const lineMat = new THREE.LineBasicMaterial({ color: 0xffa500 });
    const lineGeo = new THREE.BufferGeometry();
    const distanceLine = new THREE.Line(lineGeo, lineMat);
    scene.add(distanceLine);

    // Raycaster for interaction
    raycaster = new THREE.Raycaster();
    mouse = new THREE.Vector2();

    // Initial positions
    updatePositions();
    updateDisplay();

    // Animation loop
    function animate() {
      animationId = requestAnimationFrame(animate);

      // Update distance line
      if (distanceLine && cameraModel) {
        const positions = new Float32Array([
          CENTER.x, CENTER.y, CENTER.z,
          cameraModel.position.x, cameraModel.position.y, cameraModel.position.z
        ]);
        distanceLine.geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      }

      renderer.render(scene, camera);
    }
    animate();

    // Event handlers
    const canvas = renderer.domElement;

    function onPointerDown(e) {
      if (disabled) return;
      e.stopPropagation();
      e.preventDefault();

      const rect = canvas.getBoundingClientRect();
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObjects([rotationHandle, tiltHandle, distanceHandle]);

      if (intersects.length > 0) {
        isDragging = true;
        dragTarget = intersects[0].object;
        dragStartMouse = { x: mouse.x, y: mouse.y };

        if (dragTarget.userData.type === 'rotation') {
          dragStartValue = rotateDeg;
        } else if (dragTarget.userData.type === 'tilt') {
          dragStartValue = verticalTilt;
        } else if (dragTarget.userData.type === 'distance') {
          dragStartValue = moveForward;
        }

        dragTarget.material.emissiveIntensity = 1.0;
        dragTarget.scale.setScalar(1.3);
        canvas.style.cursor = 'grabbing';

        // Capture pointer to receive events even when mouse leaves canvas
        canvas.setPointerCapture(e.pointerId);
      }
    }

    function onPointerMove(e) {
      if (!isDragging || !dragTarget || disabled) return;
      e.stopPropagation();
      e.preventDefault();

      const THREE = window.THREE;
      const rect = canvas.getBoundingClientRect();
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

      raycaster.setFromCamera(mouse, camera);
      const intersection = new THREE.Vector3();

      if (dragTarget.userData.type === 'rotation') {
        // Use raycasting with horizontal plane (Y=0.05) to get natural arc following
        const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -0.05);
        if (raycaster.ray.intersectPlane(plane, intersection)) {
          let angle = THREE.MathUtils.radToDeg(Math.atan2(intersection.x, intersection.z));
          rotateDeg = THREE.MathUtils.clamp(-angle, -90, 90);
        }
      } else if (dragTarget.userData.type === 'tilt') {
        // Use raycasting with vertical plane at X=-0.7 (where the tilt arc is)
        const plane = new THREE.Plane(new THREE.Vector3(1, 0, 0), 0.7);
        if (raycaster.ray.intersectPlane(plane, intersection)) {
          const relY = intersection.y - CENTER.y;
          const relZ = intersection.z;
          const angle = THREE.MathUtils.radToDeg(Math.atan2(relY, relZ));
          verticalTilt = THREE.MathUtils.clamp(angle / 35, -1, 1);
        }
      } else if (dragTarget.userData.type === 'distance') {
        // Delta-based for distance (matching original example)
        const deltaY = mouse.y - dragStartMouse.y;
        moveForward = THREE.MathUtils.clamp(dragStartValue + deltaY * 12, 0, 10);
      }

      updatePositions();
      updateDisplay();
      // Don't emit change during drag - only on release for smooth interaction
    }

    function onPointerUp(e) {
      if (!isDragging) return;
      e.stopPropagation();
      e.preventDefault();

      // Release pointer capture
      if (canvas.hasPointerCapture(e.pointerId)) {
        canvas.releasePointerCapture(e.pointerId);
      }

      if (dragTarget) {
        dragTarget.material.emissiveIntensity = 0.3;
        dragTarget.scale.setScalar(1.0);
      }

      isDragging = false;
      dragTarget = null;
      canvas.style.cursor = disabled ? 'default' : 'grab';

      // Emit change only when drag ends
      emitChange();
    }

    canvas.addEventListener('pointerdown', onPointerDown);
    canvas.addEventListener('pointermove', onPointerMove);
    canvas.addEventListener('pointerup', onPointerUp);
    canvas.addEventListener('pointercancel', onPointerUp);
    // Don't end drag on pointerleave - pointer capture handles this

    canvas.style.cursor = disabled ? 'default' : 'grab';

    // Store cleanup references
    wrapper._cleanup = () => {
      canvas.removeEventListener('pointerdown', onPointerDown);
      canvas.removeEventListener('pointermove', onPointerMove);
      canvas.removeEventListener('pointerup', onPointerUp);
      canvas.removeEventListener('pointercancel', onPointerUp);
      if (animationId) cancelAnimationFrame(animationId);
      if (renderer) renderer.dispose();
    };
  }

  // Reset button
  function handleReset(e) {
    if (disabled) return;
    e.stopPropagation();
    e.preventDefault();
    rotateDeg = 0;
    moveForward = 0;
    verticalTilt = 0;
    updatePositions();
    updateDisplay();
    emitChange();
  }
  resetBtn.addEventListener('click', handleReset);

  // Stop event propagation on container
  const containerEl = container.querySelector('.camera-control-container');
  function stopEvent(e) {
    e.stopPropagation();
  }
  containerEl.addEventListener('pointerdown', stopEvent);
  containerEl.addEventListener('mousedown', stopEvent);

  // Initialize
  initScene().catch(err => {
    console.error('Failed to initialize THREE.js scene:', err);
    wrapper.innerHTML = '<div style="color: red; padding: 16px; text-align: center;">Failed to load 3D view</div>';
  });

  // Cleanup
  return () => {
    if (wrapper._cleanup) wrapper._cleanup();
    resetBtn.removeEventListener('click', handleReset);
    containerEl.removeEventListener('pointerdown', stopEvent);
    containerEl.removeEventListener('mousedown', stopEvent);
  };
}
