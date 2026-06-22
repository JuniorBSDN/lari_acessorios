from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
CORS(app)

# Configurações de Ambiente vindas da Vercel
VERCEL_BLOB_READ_WRITE_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or os.environ.get("ADMIN_PASSOWORD")
DATABASE_URL = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL_NON_POOLING")

def obter_conexao():
    if not DATABASE_URL:
        raise ValueError("A string de conexão (POSTGRES_URL) não foi configurada na Vercel.")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    conn.autocommit = True
    return conn

def inicializar_infraestrutura_banco():
    if DATABASE_URL:
        try:
            conn = obter_conexao()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS produtos (
                    id_produto VARCHAR(255) PRIMARY KEY,
                    nome VARCHAR(255) NOT NULL,
                    preco NUMERIC(10, 2) NOT NULL,
                    categoria VARCHAR(100) NOT NULL,
                    foto TEXT NOT NULL,
                    visivel BOOLEAN DEFAULT TRUE
                );
            """)
            cursor.close()
            conn.close()
            print("Infraestrutura de banco verificada/criada com sucesso.")
        except Exception as e:
            print(f"Erro ao inicializar o banco de dados: {str(e)}")

# Garante que a tabela exista ao subir a aplicação
inicializar_infraestrutura_banco()

# ROTA: Autenticação Administrativa
@app.route("/api/admin/login", methods=["POST"])
def efetuari_login_administrativo():
    dados = request.get_json() or {}
    senha_fornecida = dados.get("senha")

    if not ADMIN_PASSWORD:
        return jsonify({"error": "A senha do administrador não está configurada no ambiente da Vercel."}), 500

    if senha_fornecida == ADMIN_PASSWORD:
        return jsonify({"token": "Bearer sessao_valida_lari_premium"}), 200
    else:
        return jsonify({"error": "Senha inválida."}), 401

# ROTA: Upload de Imagens para o Vercel Blob
@app.route("/api/upload", methods=["POST"])
def processar_upload_imagem():
    token_sessao = request.headers.get("Authorization")
    if token_sessao != "Bearer sessao_valida_lari_premium":
        return jsonify({"error": "Acesso não autorizado."}), 403

    if 'foto' not in request.files:
        return jsonify({"error": "Nenhum arquivo de imagem foi enviado."}), 400

    arquivo_foto = request.files['foto']
    if arquivo_foto.filename == '':
        return jsonify({"error": "Arquivo inválido ou sem nome."}), 400

    if not VERCEL_BLOB_READ_WRITE_TOKEN:
        return jsonify({"error": "Token do Vercel Blob não está configurado."}), 500

    try:
        nome_limpo_arquivo = arquivo_foto.filename.replace(" ", "_")
        url_blob = f"https://blob.vercel-storage.com/{nome_limpo_arquivo}"

        headers_blob = {
            "Authorization": f"Bearer {VERCEL_BLOB_READ_WRITE_TOKEN}",
            "x-api-version": "2023-01-01"
        }

        conteudo_arquivo = arquivo_foto.read()
        resposta_blob = requests.put(url_blob, data=conteudo_arquivo, headers=headers_blob)

        if resposta_blob.status_code in [200, 201]:
            dados_retorno = resposta_blob.json()
            return jsonify({"url": dados_retorno.get("url")}), 200

        return jsonify({"error": "Falha na comunicação com o provedor de storage Vercel Blob."}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ROTAS: Operações do Catálogo de Produtos (GET / POST)
@app.route("/api/produtos", methods=["GET", "POST"])
def gerenciar_colecao_produtos():
    if request.method == "POST":
        token_sessao = request.headers.get("Authorization")
        if token_sessao != "Bearer sessao_valida_lari_premium":
            return jsonify({"error": "Acesso não autorizado."}), 403

        dados_produto = request.get_json() or {}
        id_produto = dados_produto.get("id_produto")
        nome = dados_produto.get("nome")
        preco = dados_produto.get("preco")
        categoria = dados_produto.get("categoria")
        foto = dados_produto.get("foto")
        visivel = dados_produto.get("visivel", True)

        if not id_produto or not nome or preco is None or not categoria or not foto:
            return jsonify({"error": "Todos os campos obrigatórios devem ser preenchidos."}), 400

        try:
            conn = obter_conexao()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO produtos (id_produto, nome, preco, categoria, foto, visivel)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id_produto) DO UPDATE 
                SET nome = EXCLUDED.nome,
                    preco = EXCLUDED.preco,
                    categoria = EXCLUDED.categoria,
                    foto = EXCLUDED.foto,
                    visivel = EXCLUDED.visivel;
            """, (str(id_produto).strip(), nome, float(preco), categoria, foto, bool(visivel)))
            cursor.close()
            conn.close()
            return jsonify({"status": "success"}), 201
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    try:
        conn = obter_conexao()
        cursor = conn.cursor()
        cursor.execute("SELECT id_produto, nome, preco, categoria, foto, visivel FROM produtos ORDER BY nome ASC;")
        registros = cursor.fetchall()
        cursor.close()
        conn.close()

        for r in registros:
            r['preco'] = float(r['preco'])

        return jsonify(registros), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ROTA: Exclusão de Produtos por ID
@app.route("/api/produtos/<path:id_prod>", methods=["DELETE"])
def remover_produto_banco(id_prod):
    token_sessao = request.headers.get("Authorization")
    if token_sessao != "Bearer sessao_valida_lari_premium":
        return jsonify({"error": "Acesso não autorizado."}), 403

    id_limpo = str(id_prod).strip()

    try:
        conn = obter_conexao()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM produtos WHERE id_produto = %s;", (id_limpo,))
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "message": "Produto deletado com sucesso."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def catch_all(path):
    return jsonify({"status": "running", "message": "LariAcessórios API Ativa"}), 200
