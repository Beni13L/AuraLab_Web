from flask import Flask, render_template, request, session, redirect, url_for
from flask_socketio import SocketIO
import pymysql
import random
import string 

app = Flask(__name__)
app.config['SECRET_KEY'] = 'AuraLab_Secreto_123' 
socketio = SocketIO(app, cors_allowed_origins="*")

def obtener_conexion():
    return pymysql.connect(
        host='auralab-db-cutauralab.i.aivencloud.com',
        port=25290,
        user='avnadmin',
        password='AVNS_IKN7Cz3kzJ8UA55COB0',
        database='defaultdb',
        ssl={'ca': 'ca.pem'},
        cursorclass=pymysql.cursors.DictCursor
    )
# ================= LOGIN =================
@app.route('/', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        conexion = obtener_conexion()
        with conexion.cursor() as cursor:
            cursor.execute("SELECT * FROM Usuarios WHERE matricula = %s AND contrasena_hash = %s", (request.form['matricula'], request.form['contrasena']))
            usuario = cursor.fetchone()
            if usuario:
                session['id_usuario'] = usuario['id_usuario']
                session['nombre'] = usuario['nombre_completo']
                session['rol'] = usuario['rol']
                conexion.close()
                
                if usuario['rol'] == 'Superadmin': 
                    return redirect(url_for('panel_superadmin'))
                elif usuario['rol'] == 'Maestro': 
                    return redirect(url_for('panel_maestro'))
                elif usuario['rol'] == 'Alumno': 
                    return redirect(url_for('portal_alumno'))
            else:
                error = "Credenciales incorrectas."
        if conexion.open: 
            conexion.close()
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ================= PORTAL Y ACCESO DEL ALUMNO =================
@app.route('/portal_alumno')
def portal_alumno():
    if 'id_usuario' not in session or session.get('rol') != 'Alumno': 
        return redirect(url_for('login'))
        
    id_alumno = session['id_usuario']
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        # Materias inscritas
        cursor.execute("""
            SELECT g.nombre_materia, g.seccion, u.nombre_completo as nombre_maestro 
            FROM Inscripciones i 
            JOIN Grupos g ON i.id_grupo = g.id_grupo 
            JOIN Usuarios u ON g.id_maestro = u.id_usuario 
            WHERE i.id_alumno = %s
        """, (id_alumno,))
        materias = cursor.fetchall()
        
        # HISTORIAL ACTUALIZADO CON EL NOMBRE DE LA MATERIA
        cursor.execute("""
            SELECT r.codigo_sala, g.nombre_materia, COUNT(CASE WHEN r.es_correcta = 1 THEN 1 END) as aciertos
            FROM Respuestas_Flash r
            JOIN Sesiones_Activas s ON r.codigo_sala = s.codigo_sala
            JOIN Grupos g ON s.id_grupo = g.id_grupo
            WHERE r.id_alumno = %s
            GROUP BY r.codigo_sala, g.nombre_materia
        """, (id_alumno,))
        historial = cursor.fetchall()
        
    conexion.close()
    return render_template('alumno.html', nombre=session['nombre'], materias=materias, historial=historial)

@app.route('/inscribir_con_codigo', methods=['POST'])
def inscribir_con_codigo():
    # Verificamos de forma estricta que sea un alumno logueado
    if 'id_usuario' not in session or session.get('rol') != 'Alumno': 
        return redirect(url_for('login'))
        
    codigo = request.form.get('codigo_clase', '').strip().upper()
    id_alumno = session['id_usuario']
    
    if not codigo:
        return redirect(url_for('portal_alumno'))

    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        # Buscamos el grupo que pertenezca a ese código de invitación
        cursor.execute("SELECT id_grupo FROM Grupos WHERE codigo_invitacion = %s", (codigo,))
        grupo = cursor.fetchone()
        
        if grupo:
            id_grupo = grupo['id_grupo']
            # Verificamos si ya está inscrito para evitar duplicados o errores
            cursor.execute("SELECT * FROM Inscripciones WHERE id_grupo = %s AND id_alumno = %s", (id_grupo, id_alumno))
            ya_inscrito = cursor.fetchone()
            
            if not ya_inscrito:
                try:
                    cursor.execute("INSERT INTO Inscripciones (id_grupo, id_alumno) VALUES (%s, %s)", (id_grupo, id_alumno))
                    conexion.commit()
                except Exception as e:
                    conexion.rollback()
                    print(f"Error al inscribir: {e}")
                    
    conexion.close()
    
    # Lo devolvemos de inmediato a su portal de alumno de forma segura
    return redirect(url_for('portal_alumno'))

@app.route('/unirse_sala', methods=['POST'])
def unirse_sala():
    if session.get('rol') != 'Alumno': 
        return redirect(url_for('login'))
        
    pin = request.form.get('codigo_sala', '').strip().upper()
    
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        # Verificamos que la sala exista (sin importar si está en espera o activa)
        cursor.execute("SELECT * FROM Sesiones_Activas WHERE codigo_sala = %s", (pin,))
        sala = cursor.fetchone()
        
    conexion.close()
    if sala:
        # Los mandamos directo a la sala de espera del alumno
        return redirect(url_for('sala_espera', pin=pin))
        
    return "La sala con ese PIN no existe o ya finalizó.", 400

@app.route('/entrar_sala', methods=['POST'])
def entrar_sala():
    pin = request.form['pin_sala'].upper().strip()
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("SELECT * FROM Sesiones_Activas WHERE codigo_sala = %s", (pin,))
        sala = cursor.fetchone()
    conexion.close()
    if sala: return redirect(url_for('sala_espera', pin=pin))
    return render_template('login.html', error="El PIN no existe.")

# ================= REGISTRO DE NUEVOS USUARIOS VÍA CÓDIGOS =================
@app.route('/registro_docente', methods=['POST'])
def registro_docente():
    nombre_pila = request.form['nombre'].strip() 
    apellidos = request.form['apellidos'].strip() 
    nombre = f"{nombre_pila} {apellidos}"
    correo = request.form['correo']
    contrasena = request.form['contrasena']
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("SELECT MAX(id_usuario) as max_id FROM Usuarios")
        res = cursor.fetchone()
        next_id = (res['max_id'] or 0) + 1
        matricula_nueva = f"DOC-{str(next_id).zfill(4)}"
        cursor.execute("INSERT INTO Usuarios (matricula, nombre_completo, correo, contrasena_hash, rol) VALUES (%s, %s, %s, %s, %s)", 
                       (matricula_nueva, nombre, correo, contrasena, 'Maestro'))
        conexion.commit()
    conexion.close()
    return redirect(url_for('login'))

@app.route('/registro_alumno_codigo', methods=['POST'])
def registro_alumno_codigo():
    codigo = request.form['codigo_clase']
    matricula = request.form['matricula'].upper().strip()
    
    # Recibimos nombre y apellidos por separado y los unimos
    nombre_pila = request.form['nombre'].strip()
    apellidos = request.form['apellidos'].strip()
    nombre_completo = f"{nombre_pila} {apellidos}"
    
    carrera = request.form['carrera']
    cuatrimestre = request.form['cuatrimestre']
    correo = request.form['correo']
    contrasena = request.form['contrasena']
    
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("SELECT id_grupo FROM Grupos WHERE codigo_invitacion = %s", (codigo,))
        grupo = cursor.fetchone()
        
        if grupo:
            cursor.execute("SELECT id_usuario FROM Usuarios WHERE matricula = %s", (matricula,))
            alumno_existente = cursor.fetchone()
            
            if alumno_existente:
                id_alumno = alumno_existente['id_usuario']
            else:
                # Insertamos el nombre_completo concatenado
                cursor.execute("INSERT INTO Usuarios (matricula, nombre_completo, correo, carrera, cuatrimestre, contrasena_hash, rol) VALUES (%s, %s, %s, %s, %s, %s, %s)", 
                               (matricula, nombre_completo, correo, carrera, cuatrimestre, contrasena, 'Alumno'))
                id_alumno = cursor.lastrowid
                
            cursor.execute("SELECT * FROM Inscripciones WHERE id_grupo = %s AND id_alumno = %s", (grupo['id_grupo'], id_alumno))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO Inscripciones (id_grupo, id_alumno) VALUES (%s, %s)", (grupo['id_grupo'], id_alumno))
            conexion.commit()
    conexion.close()
    
    return redirect(url_for('login'))

# ================= CRUD SUPERADMIN =================
@app.route('/panel_superadmin')
def panel_superadmin():
    if session.get('rol') != 'Superadmin': return redirect(url_for('login'))
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("SELECT * FROM Usuarios")
        usuarios = cursor.fetchall()
        cursor.execute("SELECT MAX(id_usuario) as max_id FROM Usuarios")
        res = cursor.fetchone()
        next_id = (res['max_id'] or 0) + 1
    conexion.close()
    return render_template('superadmin.html', nombre=session['nombre'], usuarios=usuarios, mi_id=session['id_usuario'], next_id=next_id)

@app.route('/crear_usuario', methods=['POST'])
def crear_usuario():
    if session.get('rol') != 'Superadmin': return redirect(url_for('login'))
    carrera = request.form.get('carrera', '')
    cuatrimestre = request.form.get('cuatrimestre', '')
    if request.form['rol'] != 'Alumno':
        carrera = ''
        cuatrimestre = ''
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("INSERT INTO Usuarios (matricula, nombre_completo, correo, carrera, cuatrimestre, contrasena_hash, rol) VALUES (%s, %s, %s, %s, %s, %s, %s)", 
                       (request.form['matricula'], request.form['nombre'], request.form['correo'], carrera, cuatrimestre, request.form['contrasena'], request.form['rol']))
        conexion.commit()
    conexion.close()
    return redirect(url_for('panel_superadmin'))

@app.route('/actualizar_usuario', methods=['POST'])
def actualizar_usuario():
    if session.get('rol') != 'Superadmin': return redirect(url_for('login'))
    carrera = request.form.get('carrera', '')
    cuatrimestre = request.form.get('cuatrimestre', '')
    if request.form['rol'] != 'Alumno':
        carrera = ''
        cuatrimestre = ''
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("UPDATE Usuarios SET matricula=%s, nombre_completo=%s, correo=%s, carrera=%s, cuatrimestre=%s, contrasena_hash=%s, rol=%s WHERE id_usuario=%s", 
                       (request.form['matricula'], request.form['nombre'], request.form['correo'], carrera, cuatrimestre, request.form['contrasena'], request.form['rol'], request.form['id_usuario']))
        conexion.commit()
    conexion.close()
    return redirect(url_for('panel_superadmin'))

@app.route('/eliminar_usuario/<int:id>')
def eliminar_usuario(id):
    if session.get('rol') != 'Superadmin': return redirect(url_for('login'))
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("DELETE FROM Usuarios WHERE id_usuario = %s", (id,))
        conexion.commit()
    conexion.close()
    return redirect(url_for('panel_superadmin'))

# ================= PANEL MAESTRO (GRUPOS) =================
@app.route('/panel_maestro')
def panel_maestro():
    if session.get('rol') != 'Maestro': return redirect(url_for('login'))
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("SELECT * FROM Grupos WHERE id_maestro = %s", (session['id_usuario'],))
        grupos = cursor.fetchall()
    conexion.close()
    return render_template('maestro.html', nombre=session['nombre'], grupos=grupos)

@app.route('/crear_grupo', methods=['POST'])
def crear_grupo():
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("INSERT INTO Grupos (id_maestro, nombre_materia, seccion) VALUES (%s, %s, %s)", (session['id_usuario'], request.form['nombre_materia'], request.form['seccion']))
        conexion.commit()
    conexion.close()
    return redirect(url_for('panel_maestro'))

@app.route('/actualizar_grupo', methods=['POST'])
def actualizar_grupo():
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("UPDATE Grupos SET nombre_materia=%s, seccion=%s WHERE id_grupo=%s", (request.form['nombre_materia'], request.form['seccion'], request.form['id_grupo']))
        conexion.commit()
    conexion.close()
    return redirect(url_for('panel_maestro'))

@app.route('/eliminar_grupo/<int:id>')
def eliminar_grupo(id):
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("DELETE FROM Grupos WHERE id_grupo = %s", (id,))
        conexion.commit()
    conexion.close()
    return redirect(url_for('panel_maestro'))

@app.route('/lanzar_examen_parcial/<int:id_grupo>/<string:parcial>', methods=['POST'])
def lanzar_examen_parcial(id_grupo, parcial):
    if 'id_usuario' not in session or session.get('rol') != 'Maestro': 
        return redirect(url_for('login'))
        
    pin = f"EXAM-{''.join(random.choices(string.ascii_uppercase + string.digits, k=4))}"
    
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("INSERT INTO Sesiones_Activas (id_maestro, id_grupo, codigo_sala, estado) VALUES (%s, %s, %s, %s)", 
                       (session['id_usuario'], id_grupo, pin, 'En_Espera'))
        
        cursor.execute("SELECT * FROM Banco_Preguntas WHERE id_grupo = %s AND parcial = %s", (id_grupo, parcial))
        preguntas_banco = cursor.fetchall()
        
        for p in preguntas_banco:
            cursor.execute("""
                INSERT INTO Preguntas_Flash (codigo_sala, texto_pregunta, opcion_a, opcion_b, opcion_c, opcion_d, respuesta_correcta) 
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (pin, p['texto_pregunta'], p['opcion_a'], p['opcion_b'], p['opcion_c'], p['opcion_d'], p['respuesta_correcta']))
                
        conexion.commit()
    conexion.close()
    
    return redirect(url_for('sala_activa', pin=pin))

@app.route('/eliminar_examen/<pin>')
def eliminar_examen(pin):
    if 'id_usuario' not in session or session.get('rol') != 'Maestro': 
        return redirect(url_for('login'))
        
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        # Borramos las respuestas asociadas a esta sala
        cursor.execute("DELETE FROM Respuestas_Flash WHERE codigo_sala = %s", (pin,))
        # Borramos las preguntas flash de esta sala
        cursor.execute("DELETE FROM Preguntas_Flash WHERE codigo_sala = %s", (pin,))
        # Borramos la sesión activa / examen aplicado
        cursor.execute("DELETE FROM Sesiones_Activas WHERE codigo_sala = %s", (pin,))
        conexion.commit()
    conexion.close()
    
    # Redirigimos de regreso al grupo (buscamos a qué grupo pertenecía la sesión para volver exacto)
    return redirect(request.referrer or url_for('panel_maestro'))

# ================= INTERIOR DEL GRUPO (ALUMNOS Y PREGUNTAS) =================
@app.route('/grupo/<int:id_grupo>')
def detalle_grupo(id_grupo):
    if 'id_usuario' not in session or session.get('rol') != 'Maestro': 
        return redirect(url_for('login'))
        
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("SELECT * FROM Grupos WHERE id_grupo = %s", (id_grupo,))
        grupo = cursor.fetchone()
        
        cursor.execute("SELECT U.id_usuario, U.matricula, U.nombre_completo, U.correo FROM Inscripciones I JOIN Usuarios U ON I.id_alumno = U.id_usuario WHERE I.id_grupo = %s", (id_grupo,))
        alumnos = cursor.fetchall()
        
        cursor.execute("SELECT * FROM Banco_Preguntas WHERE materia = %s", (grupo['nombre_materia'],))
        preguntas = cursor.fetchall()
        
        # HISTORIAL DE EXÁMENES VINCULADO AL GRUPO
        cursor.execute("SELECT * FROM Sesiones_Activas WHERE id_grupo = %s ORDER BY codigo_sala DESC", (id_grupo,))
        sesiones = cursor.fetchall()
        
    conexion.close()
    return render_template('grupo_detalle.html', nombre=session['nombre'], grupo=grupo, alumnos=alumnos, preguntas=preguntas, sesiones=sesiones)

@app.route('/generar_codigo_clase/<int:id_grupo>')
def generar_codigo_clase(id_grupo):
    if 'id_usuario' not in session or session.get('rol') != 'Maestro': 
        return redirect(url_for('login'))
        
    codigo = f"ALUM-{''.join(random.choices(string.ascii_uppercase + string.digits, k=4))}"
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("UPDATE Grupos SET codigo_invitacion = %s WHERE id_grupo = %s", (codigo, id_grupo))
        conexion.commit()
    conexion.close()
    return redirect(url_for('detalle_grupo', id_grupo=id_grupo))

@app.route('/inscribir_alumno', methods=['POST'])
def inscribir_alumno():
    id_grupo = request.form['id_grupo']
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("SELECT id_usuario FROM Usuarios WHERE matricula = %s AND rol = 'Alumno'", (request.form['matricula_alumno'],))
        alumno = cursor.fetchone()
        if alumno:
            try:
                cursor.execute("INSERT INTO Inscripciones (id_grupo, id_alumno) VALUES (%s, %s)", (id_grupo, alumno['id_usuario']))
                conexion.commit()
            except: pass
    conexion.close()
    return redirect(url_for('detalle_grupo', id_grupo=id_grupo))

@app.route('/expulsar_alumno/<int:id_grupo>/<int:id_alumno>')
def expulsar_alumno(id_grupo, id_alumno):
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("DELETE FROM Inscripciones WHERE id_grupo = %s AND id_alumno = %s", (id_grupo, id_alumno))
        conexion.commit()
    conexion.close()
    return redirect(url_for('detalle_grupo', id_grupo=id_grupo))

@app.route('/crear_pregunta', methods=['POST'])
def crear_pregunta():
    id_grupo = request.form['id_grupo']
    materia = request.form['materia']
    pregunta = request.form['texto_pregunta']
    op_a = request.form['opcion_a']
    op_b = request.form['opcion_b']
    op_c = request.form['opcion_c']
    op_d = request.form['opcion_d']
    correcta = request.form['respuesta_correcta']
    parcial = request.form['parcial']
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("""
            INSERT INTO Banco_Preguntas (id_grupo, materia, texto_pregunta, opcion_a, opcion_b, opcion_c, opcion_d, respuesta_correcta, parcial)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (id_grupo, materia, pregunta, op_a, op_b, op_c, op_d, correcta, parcial))
        conexion.commit()
    conexion.close()
    return redirect(url_for('detalle_grupo', id_grupo=id_grupo))

@app.route('/editar_pregunta', methods=['POST'])
def editar_pregunta():
    id_pregunta = request.form['id_pregunta']
    id_grupo = request.form['id_grupo']
    pregunta = request.form['texto_pregunta']
    op_a = request.form['opcion_a']
    op_b = request.form['opcion_b']
    op_c = request.form['opcion_c']
    op_d = request.form['opcion_d']
    correcta = request.form['respuesta_correcta']
    parcial = request.form['parcial']
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("""
            UPDATE Banco_Preguntas 
            SET texto_pregunta = %s, opcion_a = %s, opcion_b = %s, opcion_c = %s, opcion_d = %s, respuesta_correcta = %s, parcial = %s
            WHERE id_pregunta = %s
        """, (pregunta, op_a, op_b, op_c, op_d, correcta, parcial, id_pregunta))
        conexion.commit()
    conexion.close()
    return redirect(url_for('detalle_grupo', id_grupo=id_grupo))

@app.route('/eliminar_pregunta/<int:id>/<int:id_grupo>')
def eliminar_pregunta(id, id_grupo):
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("DELETE FROM Banco_Preguntas WHERE id_pregunta = %s", (id,))
        conexion.commit()
    conexion.close()
    return redirect(url_for('detalle_grupo', id_grupo=id_grupo))

# ================= SALAS FLASH (LÓGICA DEL PROFESOR) =================
@app.route('/crear_sala', methods=['POST'])
def crear_sala():
    id_grupo = request.form['id_grupo'] 
    pin = f"CUT-{''.join(random.choices(string.ascii_uppercase + string.digits, k=4))}"
    
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("INSERT INTO Sesiones_Activas (id_maestro, id_grupo, codigo_sala, estado) VALUES (%s, %s, %s, %s)", 
                       (session['id_usuario'], id_grupo, pin, 'En_Espera'))
        
        for i in range(1, 21):
            pregunta = request.form.get(f'pregunta_{i}')
            if pregunta:
                op_a = request.form.get(f'opcion_a_{i}')
                op_b = request.form.get(f'opcion_b_{i}')
                op_c = request.form.get(f'opcion_c_{i}')
                op_d = request.form.get(f'opcion_d_{i}')
                correcta = request.form.get(f'correcta_{i}')
                
                cursor.execute("""
                    INSERT INTO Preguntas_Flash (codigo_sala, texto_pregunta, opcion_a, opcion_b, opcion_c, opcion_d, respuesta_correcta) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (pin, pregunta, op_a, op_b, op_c, op_d, correcta))
                
        conexion.commit()
    conexion.close()
    
    return redirect(url_for('sala_activa', pin=pin))

@app.route('/sala_activa/<pin>')
def sala_activa(pin):
    if 'id_usuario' not in session: return redirect(url_for('login'))
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("SELECT * FROM Sesiones_Activas WHERE codigo_sala = %s AND id_maestro = %s", (pin, session['id_usuario']))
        sala = cursor.fetchone()
    conexion.close()
    
    if not sala: return "Sala no encontrada o no tienes permiso para verla.", 404
    return render_template('sala_activa.html', pin=pin, sala=sala)

@app.route('/iniciar_examen/<pin>', methods=['POST'])
def iniciar_examen(pin):
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("UPDATE Sesiones_Activas SET estado = 'Activa' WHERE codigo_sala = %s", (pin,))
        conexion.commit()
    conexion.close()
    return redirect(url_for('sala_activa', pin=pin))

@app.route('/cerrar_examen/<pin>', methods=['POST'])
def cerrar_examen(pin):
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("UPDATE Sesiones_Activas SET estado = 'Cerrada' WHERE codigo_sala = %s", (pin,))
        conexion.commit()
    conexion.close()
    return redirect(url_for('radar_dudas', pin=pin))

@app.route('/radar_dudas/<pin>')
def radar_dudas(pin):
    if 'id_usuario' not in session: return redirect(url_for('login'))
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        # 1. Estadísticas globales por pregunta (agregando opciones)
        cursor.execute("""
            SELECT p.id_pregunta_flash, p.texto_pregunta, p.opcion_a, p.opcion_b, p.opcion_c, p.opcion_d, p.respuesta_correcta,
                   COALESCE(SUM(CASE WHEN r.es_correcta = 1 THEN 1 ELSE 0 END), 0) as aciertos,
                   COALESCE(SUM(CASE WHEN r.es_correcta = 0 THEN 1 ELSE 0 END), 0) as errores
            FROM Preguntas_Flash p
            LEFT JOIN Respuestas_Flash r ON p.id_pregunta_flash = r.id_pregunta_flash
            WHERE p.codigo_sala = %s
            GROUP BY p.id_pregunta_flash, p.texto_pregunta, p.opcion_a, p.opcion_b, p.opcion_c, p.opcion_d, p.respuesta_correcta
        """, (pin,))
        estadisticas = cursor.fetchall()

        # 2. Calificaciones individuales
        cursor.execute("""
            SELECT u.id_usuario as id_alumno, u.matricula, u.nombre_completo,
                   COALESCE(SUM(CASE WHEN r.es_correcta = 1 THEN 1 ELSE 0 END), 0) as aciertos
            FROM Usuarios u
            JOIN Respuestas_Flash r ON u.id_usuario = r.id_alumno
            WHERE r.codigo_sala = %s
            GROUP BY u.id_usuario, u.matricula, u.nombre_completo
            ORDER BY u.nombre_completo ASC
        """, (pin,))
        calificaciones = cursor.fetchall()
        
        # 3. Detalle de respuestas para la ventana Modal de Alumnos
        cursor.execute("""
            SELECT r.id_alumno, p.texto_pregunta, p.respuesta_correcta, r.respuesta_elegida, r.es_correcta,
                   p.opcion_a, p.opcion_b, p.opcion_c, p.opcion_d
            FROM Respuestas_Flash r
            JOIN Preguntas_Flash p ON r.id_pregunta_flash = p.id_pregunta_flash
            WHERE r.codigo_sala = %s
        """, (pin,))
        detalles_raw = cursor.fetchall()
        
        detalles_por_alumno = {}
        for d in detalles_raw:
            id_al = d['id_alumno']
            if id_al not in detalles_por_alumno:
                detalles_por_alumno[id_al] = []
            detalles_por_alumno[id_al].append(d)

        # 4. NUEVO: Detalle de respuestas por cada pregunta (para saber qué contestó cada alumno en esa pregunta específica)
        cursor.execute("""
            SELECT r.id_pregunta_flash, u.matricula, u.nombre_completo, r.respuesta_elegida, r.es_correcta
            FROM Respuestas_Flash r
            JOIN Usuarios u ON r.id_alumno = u.id_usuario
            WHERE r.codigo_sala = %s
        """, (pin,))
        respuestas_por_pregunta_raw = cursor.fetchall()
        
        alumnos_por_pregunta = {}
        for rp in respuestas_por_pregunta_raw:
            id_preg = rp['id_pregunta_flash']
            if id_preg not in alumnos_por_pregunta:
                alumnos_por_pregunta[id_preg] = []
            alumnos_por_pregunta[id_preg].append(rp)

        # 5. Total de preguntas
        cursor.execute("SELECT COUNT(*) as total FROM Preguntas_Flash WHERE codigo_sala = %s", (pin,))
        resultado_total = cursor.fetchone()
        total_preguntas = resultado_total['total'] if resultado_total else 0

    conexion.close()
    return render_template('radar_dudas.html', pin=pin, estadisticas=estadisticas, 
                           calificaciones=calificaciones, total_preguntas=total_preguntas, 
                           detalles=detalles_por_alumno, alumnos_por_pregunta=alumnos_por_pregunta)

# ================= EXAMEN FLASH (LÓGICA DEL ALUMNO) =================
@app.route('/sala_espera/<pin>')
def sala_espera(pin):
    if 'id_usuario' not in session: return redirect(url_for('login'))
    return render_template('sala_espera.html', pin=pin, nombre_alumno=session['nombre'])

@app.route('/verificar_estado_sala/<pin>')
def verificar_estado_sala(pin):
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("SELECT estado FROM Sesiones_Activas WHERE codigo_sala = %s", (pin,))
        sala = cursor.fetchone()
    conexion.close()
    if sala: return {"estado": sala['estado']}
    return {"estado": "Cerrada"}

@app.route('/examen_flash/<pin>')
def examen_flash(pin):
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("SELECT * FROM Preguntas_Flash WHERE codigo_sala = %s", (pin,))
        preguntas = cursor.fetchall()
    conexion.close()
    return render_template('examen_flash.html', pin=pin, preguntas=preguntas)

@app.route('/guardar_respuestas_flash', methods=['POST'])
def guardar_respuestas_flash():
    pin = request.form['pin']
    id_usuario = session['id_usuario'] 
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        for key, value in request.form.items():
            if key.startswith('pregunta_'):
                id_pregunta = key.split('_')[1]
                respuesta_elegida = value
                
                cursor.execute("SELECT respuesta_correcta FROM Preguntas_Flash WHERE id_pregunta_flash = %s", (id_pregunta,))
                res_db = cursor.fetchone()
                
                if res_db:
                    es_correcta = (res_db['respuesta_correcta'] == respuesta_elegida)
                    cursor.execute("""
                        INSERT INTO Respuestas_Flash (codigo_sala, id_alumno, id_pregunta_flash, respuesta_elegida, es_correcta)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (pin, id_usuario, id_pregunta, respuesta_elegida, es_correcta))
        conexion.commit()
    conexion.close()
    return redirect(url_for('diagnostico_alumno', pin=pin))

@app.route('/diagnostico_alumno/<pin>')
def diagnostico_alumno(pin):
    if 'id_usuario' not in session or session.get('rol') != 'Alumno': 
        return redirect(url_for('login'))
        
    id_usuario = session['id_usuario']
    conexion = obtener_conexion()
    with conexion.cursor() as cursor:
        cursor.execute("""
            SELECT p.texto_pregunta, p.respuesta_correcta, r.respuesta_elegida, r.es_correcta,
                   p.opcion_a, p.opcion_b, p.opcion_c, p.opcion_d
            FROM Respuestas_Flash r
            JOIN Preguntas_Flash p ON r.id_pregunta_flash = p.id_pregunta_flash
            WHERE r.codigo_sala = %s AND r.id_alumno = %s
        """, (pin, id_usuario))
        respuestas = cursor.fetchall()
        
        aciertos = sum(1 for r in respuestas if r['es_correcta'])
        total = len(respuestas)
    conexion.close()
    return render_template('diagnostico_alumno.html', pin=pin, respuestas=respuestas, aciertos=aciertos, total=total)

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)
