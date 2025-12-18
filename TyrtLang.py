import re
import collections
import sys
import os 

# --- I. Classes Auxiliares e de Instância ---

class TyrtInstance:
    """ Representa uma instância (objeto) de uma classe TyrtLang. """
    
    DUNDER_MAP = {
        '+': '___add___', '-': '___sub___', '*': '___mul___', '/': '___truediv___', 
        '==': '___eq___', '!=': '___ne___', '>': '___gt___', '<': '___lt___', 
        'getitem': '___getitem___', 'setitem': '___setitem___',
    }

    def __init__(self, class_name, methods):
        self.class_name = class_name
        self.instance_variables = {}
        self.methods = methods

    def __repr__(self): return f"<TyrtInstance: {self.class_name}>"
    def __str__(self): return f"Objeto {self.class_name} {{{', '.join(self.instance_variables.keys())}}}"

    def call_method(self, interpreter, method_name, args_list):
        """ Executa um método de instância. """
        if method_name not in self.methods:
            # Note: Usamos o TyrtRuntimeError padrão aqui, pois é uma chamada de método que falhou.
            raise interpreter.InvalidMethodCall(f"Método '{method_name}' não encontrado na classe '{self.class_name}'.")

        params, body = self.methods[method_name]
        expected_params = params[1:] if params and params[0] == 'self' else params

        if len(expected_params) != len(args_list):
            raise interpreter.InvalidMethodCall(f"Método '{method_name}': {len(args_list)} argumentos dados, mas {len(expected_params)} esperados.")

        func_scope = dict(zip(expected_params, args_list))
        return interpreter.execute_block(body, func_scope, instance=self)

    def handle_operator(self, interpreter, op_symbol, other_obj=None):
        """ 
        Trata a sobrecarga de operadores (Dunder methods). 
        Lança TyrtRuntimeError.NotImplementedError se o operador não for definido.
        """
        dunder_method = self.DUNDER_MAP.get(op_symbol)
        
        if not dunder_method or dunder_method not in self.methods:
            # LANÇA A EXCEÇÃO TyrtLang ESPECÍFICA (NotImplementedError)
            raise interpreter.NotImplementedError(f"O operador '{op_symbol}' não está implementado na classe '{self.class_name}'.")
            
        if op_symbol in ['print', 'len']: return self.call_method(interpreter, dunder_method, [])
        else: return self.call_method(interpreter, dunder_method, [other_obj])


# --- II. Interpretador TyrtLang (Núcleo) ---

class TyrtLangInterpreter:
    TYRT = 10**190000

    # --- Exceções TyrtLang ---
    class LineNoRecognized(Exception): pass
    class InvalidSyntax(Exception): pass
    class InvalidExpression(Exception): pass
    class TyrtError(Exception): pass
    class TyrtRuntimeError(TyrtError): pass
    class VariableNotDefined(TyrtRuntimeError): pass
    class ConstantReassignment(TyrtRuntimeError): pass
    class InvalidMethodCall(TyrtRuntimeError): pass
    class NotImplementedError(TyrtRuntimeError): pass # <-- NOVA EXCEÇÃO
    class LoopBreakTyrt(Exception): pass
    class LoopContinueTyrt(Exception): pass

    def __init__(self):
        self.variables = {}; self.functions = {}; self.classes = {}; self.constants = {} 
        
        # Blocos de Controle de Fluxo
        self._in_if_block = False; self._current_if_is_active = False; self._current_if_block_lines = []
        self._in_for_block = False; self._for_block = []; self._for_var = None; self._for_start = None; self._for_end = None
        self._in_while_block = False; self._while_block = []; self._while_condition = None
        
        # Blocos de Definição de Estruturas
        self._in_func_block = False; self._func_block = []; self._func_name = None; self._func_params = []
        self._in_class_block = False; self._class_name = None; self._class_methods = {}
        
        # Blocos Try/Except/Now (com suporte a 'Except as erro')
        self._in_try_block = False; self._try_block = []
        self._in_except_block = False; self._except_block = []; self._except_var_name = None 
        self._in_now_block = False; self._now_block = []
        
        self._current_line_number = 0

    # ----------------------------------------
    # A. MÉTODO PRINCIPAL DE EXECUÇÃO (.run())
    # ----------------------------------------
    def run(self, code_source):
        """ Carrega e executa o código-fonte TyrtLang (.tyrt ou .t). """
        lines = []
        VALID_EXTENSIONS = ('.tyrt', '.t')

        if isinstance(code_source, str):
            is_file_path = '\n' not in code_source and (code_source.endswith(VALID_EXTENSIONS) or '/' in code_source or '\\' in code_source)
            
            if is_file_path:
                if not code_source.endswith(VALID_EXTENSIONS):
                     print(f"ERRO DE ARQUIVO: O interpretador TyrtLang só executa arquivos com extensão {VALID_EXTENSIONS}.")
                     return
                try:
                    with open(code_source, 'r', encoding='utf-8') as f: lines = f.readlines()
                    print(f"--- TyrtLang: Carregando arquivo executável '{code_source}' ---")
                except FileNotFoundError: lines = code_source.split('\n')
                except Exception as e: print(f"ERRO DE LEITURA: Não foi possível ler o arquivo: {e}"); return
            else:
                lines = code_source.split('\n')
                print("--- TyrtLang: Executando código em string ---")
        else:
            print("ERRO FATAL: A fonte do código deve ser uma string.")
            return

        print("\n--- TyrtLang Interpreter V34.0 (Completo) Iniciado ---")
        
        try:
            for line_number, line in enumerate(lines):
                self._current_line_number = line_number + 1
                self.execute_line(line)
        
        except self.TyrtError as e:
            print(f"\nERRO DE EXECUÇÃO NÃO TRATADO (Linha {self._current_line_number}): {e.__class__.__name__}: {e}")
        except Exception as e:
            print(f"\nERRO INTERNO DO INTERPRETADOR (Linha {self._current_line_number}): {e.__class__.__name__}: {e}")
            
        print("--- TyrtLang Finalizado ---\n")

    # ----------------------------------------
    # B. EXECUÇÃO DE LINHA (execute_line)
    # ----------------------------------------
    def execute_line(self, line, current_instance=None):
        line = line.strip()

        # 1. Comentário TyrtLang (/0)
        if line.startswith("/0") or line == "": return
        
        if line == "}": self.execute_block_end(line); return
        
        # 2. Lógica de Captura de Blocos (Encadeamento)
        if self._in_if_block or self._in_for_block or self._in_while_block or self._in_func_block or self._in_class_block or self._in_try_block or self._in_except_block or self._in_now_block:
             if self._in_if_block: self._current_if_block_lines.append(line)
             elif self._in_for_block: self._for_block.append(line)
             elif self._in_while_block: self._while_block.append(line)
             elif self._in_func_block or self._in_class_block: self._func_block.append(line)
             elif self._in_try_block: self._try_block.append(line)
             elif self._in_except_block: self._except_block.append(line)
             elif self._in_now_block: self._now_block.append(line)
             return

        # 3. Declaração de Blocos (Início)
        if line.startswith("Try"): self._in_try_block = True; self._try_block = []; self._except_block = []; self._now_block = []; self._except_var_name = None; return
        
        if line.startswith("Except"): 
             match = re.match(r"Except\s+as\s+(\w+)\s*\{?", line)
             if not match: 
                 if line.strip() == "Except {": self._except_var_name = "tyrt_error_obj"
                 else: raise self.InvalidSyntax("Sintaxe de Except inválida. Use 'Except as nome_var {' ou 'Except {'.")
             else:
                 self._except_var_name = match.groups()[0] # Captura o nome da variável 'as'
                 
             self._in_except_block = True; self._except_block = []; return
             
        if line.startswith("Now"): self._in_now_block = True; self._now_block = []; return
        
        if line.startswith("entr_i"): 
            match = re.match(r"entr_i\s*(\w+)\s*ty\s*(\d+):(\d+)\s*(_CS-TINK)?\s*\{", line)
            if not match: raise self.InvalidSyntax("Sintaxe de entr_i inválida.")
            self._for_var, self._for_start, self._for_end = match.groups()[0], match.groups()[1], match.groups()[2]
            self._in_for_block = True; self._for_block = []; return
        if line.startswith("/1"): 
            if not line.endswith("{"): raise self.InvalidSyntax("Bloco /1 deve terminar com '{'.")
            self._while_condition = line[len("/1"): -1].strip(); self._in_while_block = True; self._while_block = []; return
            
        if line.startswith("BILHETE_NADA"):
            if not line.endswith("{"): raise self.InvalidSyntax("Bloco BILHETE_NADA deve terminar com '{'.")
            self._in_if_block = True; self._current_if_block_lines = [];
            self._current_if_is_active = self.eval_condition(line[len("BILHETE_NADA"): -1].strip())
            return
            
        if line.startswith("class "):
             match = re.match(r"class\s+(\w+)\s*\{", line)
             if not match: raise self.InvalidSyntax("Sintaxe de classe inválida.")
             self._in_class_block = True; self._class_name = match.groups()[0]; self._class_methods = {}; return
        if line.startswith("func "):
            match = re.match(r"func\s+(\w+)\s*\((.*)\)\s*\{", line)
            if not match: raise self.InvalidSyntax("Sintaxe de função inválida.")
            self._in_func_block = True; self._func_name = match.groups()[0]; 
            self._func_params = [p.strip() for p in match.groups()[1].split(',') if p.strip()]; self._func_block = []; return

        # 4. Comandos e Atribuições
        if line.startswith("tyrt "):
            assign_part = line[5:].strip()
            if "=" in assign_part:
                var_expr, expr = assign_part.split("=", 1); var_expr = var_expr.strip()
                new_value = self.eval_expr(expr, current_instance=current_instance)
                
                # ... (Atribuição de instância/indexação - mantida a partir do original)
                if current_instance and var_expr.startswith("self."):
                    current_instance.instance_variables[var_expr[len("self."):].strip()] = new_value
                    return
                match_index_assign = re.match(r"(\w+)\s*\[(.*)\]$", var_expr)
                if match_index_assign:
                    var_name, index_expr = match_index_assign.groups()
                    if var_name not in self.variables: raise self.VariableNotDefined(f"Coleção '{var_name}' não definida.")
                    collection = self.variables[var_name]
                    index_value = self.eval_expr(index_expr)
                    if isinstance(collection, TyrtInstance):
                        if '___setitem___' in collection.methods:
                             collection.call_method(self, '___setitem___', [index_value, new_value])
                             return
                    if isinstance(collection, (list, dict)):
                         collection[index_value] = new_value
                         return

                var = var_expr
                if var in self.constants: raise self.ConstantReassignment(f"Constante '{var}' é imutável.")
                self.variables[var] = new_value
                return

        if line == "loop.break": raise self.LoopBreakTyrt()
        if line == "loop.continue": raise self.LoopContinueTyrt()
        if line.startswith("return_object"): pass 

        if line.startswith("print|["):
            expr = line[len("print|["): -1].strip()
            print_val = self.eval_expr(expr, current_instance=current_instance)
            print(print_val)
            return

        if "(" in line and line.endswith(")"):
            try:
                self.eval_expr(line, current_instance=current_instance)
                return
            except self.TyrtError:
                pass
            
        raise self.LineNoRecognized(f"Linha não reconhecida: {line}")
        
    # ----------------------------------------
    # C. AVALIAÇÃO DE EXPRESSÃO (eval_expr) - Sem alterações na lógica central
    # ----------------------------------------
    def eval_expr(self, expr, local_vars=None, current_instance=None):
        expr = expr.strip()
        scope = self.variables.copy(); scope.update(self.constants) 
        if local_vars: scope.update(local_vars)

        # 1. Leitura de Variável de Instância (self.var)
        if current_instance and expr.startswith("self."):
            var_instance_name = expr[len("self."):].strip()
            if var_instance_name in current_instance.instance_variables: return current_instance.instance_variables[var_instance_name]
            else: raise self.VariableNotDefined(f"Variável de instância 'self.{var_instance_name}' não definida.")
                
        # 2. Chamada de Função/Método/Instanciação/Coleções
        if "(" in expr and expr.endswith(")"):
            
            # --- Chamada de Método (Objeto/Nativo) ---
            if "." in expr:
                obj_expr, method_call = expr.rsplit(".", 1)
                method_name, args_str = method_call.split("(", 1)
                base_obj = self.eval_expr(obj_expr, local_vars, current_instance)
                args_list = [self.eval_expr(a.strip(), local_vars, current_instance) for a in args_str[:-1].split(',') if a.strip()]

                if isinstance(base_obj, list):
                    if method_name == "len": return len(base_obj)
                    elif method_name == "append": 
                        if len(args_list) != 1: raise self.InvalidMethodCall("append() espera 1 argumento.")
                        base_obj.append(args_list[0]); return base_obj
                    elif method_name == "pop": 
                        if len(args_list) > 1: raise self.InvalidMethodCall("pop() espera 0 ou 1 argumento (index).")
                        index = int(args_list[0]) if args_list else -1
                        try: return base_obj.pop(index)
                        except IndexError: raise self.TyrtRuntimeError(f"Índice {index} fora dos limites para pop().")
                    else: raise self.InvalidMethodCall(f"Método de lista nativo não reconhecido: {method_name}")

                if isinstance(base_obj, TyrtInstance):
                     if method_name in base_obj.methods: return base_obj.call_method(self, method_name, args_list)

            # --- Funções Nativas (I/O, Instanciação e Funções TyrtLang) ---
            match_native_func = re.match(r"(\w+)\s*\((.*)\)$", expr)
            if match_native_func:
                func_name, args_str = match_native_func.groups()
                args = [self.eval_expr(a.strip(), local_vars, current_instance) for a in args_str.split(',') if a.strip()]

                if func_name == "read_file":
                    if len(args) != 1 or not isinstance(args[0], str): raise self.InvalidMethodCall("read_file() espera 1 argumento: o caminho do arquivo (string).")
                    try:
                        with open(args[0], 'r', encoding='utf-8') as f: return f.read() 
                    except FileNotFoundError: raise self.TyrtRuntimeError(f"Arquivo não encontrado: {args[0]}")
                    except Exception as e: raise self.TyrtRuntimeError(f"Erro ao ler arquivo: {e}")
                
                if func_name in self.functions:
                    params, body = self.functions[func_name]
                    if len(params) != len(args): raise self.InvalidMethodCall(f"Função '{func_name}' espera {len(params)} argumentos.")
                    func_scope = dict(zip(params, args))
                    return self.execute_block(body, func_scope, instance=current_instance)
                
                if func_name in self.classes:
                    cls_methods = self.classes[func_name]
                    new_instance = TyrtInstance(func_name, cls_methods)
                    if '___init___' in cls_methods: new_instance.call_method(self, '___init___', args)
                    return new_instance

            # --- Coleções ---
            if expr.startswith(".lista("): return [self.eval_expr(a.strip()) for a in expr[len(".lista("):-1].split(',') if a.strip()]
            if expr.startswith("#dicionario("): return {} 

        # 3. Operadores Aritméticos e de Comparação
        for op in ['+', '==', '>', '<']:
            if f" {op} " in expr:
                left_expr, right_expr = expr.split(f" {op} ", 1)
                left_val = self.eval_expr(left_expr, local_vars, current_instance)
                right_val = self.eval_expr(right_expr, local_vars, current_instance)

                if isinstance(left_val, TyrtInstance):
                    # Se for TyrtInstance, usa handle_operator (que lança NotImplementedError)
                    result = left_val.handle_operator(self, op, right_val) 
                    if result is not NotImplemented: return result
                
                if op == '+': return left_val + right_val
                if op == '==': return left_val == right_val
                if op == '>': return left_val > right_val
                if op == '<': return left_val < right_val

        # 4. Acesso a Índice/Chave
        if re.search(r"\[.+?\]$", expr):
            match = re.match(r"(\w+)\s*\[(.*)\]$", expr)
            if match:
                var_name, index_expr = match.groups()
                collection = scope.get(var_name)
                if collection is None: raise self.VariableNotDefined(f"Coleção '{var_name}' não definida.")
                index_value = self.eval_expr(index_expr)

                if isinstance(collection, TyrtInstance):
                    result = collection.handle_operator(self, 'getitem', index_value)
                    if result is not NotImplemented: return result
                        
                if isinstance(collection, (list, dict)): return collection[index_value]
        
        # 5. Literais, Constantes, Variáveis
        if expr in scope: return scope[expr]
        if re.match(r'^-?\d+$', expr): return int(expr)
        if re.match(r'^".*"$', expr): return expr.strip('"')

        raise self.VariableNotDefined(f"Expressão/Variável inválida: {expr}")
        
    # ----------------------------------------
    # D. PROCESSAMENTO DE BLOCOS (Controle de Fluxo e Escopo)
    # ----------------------------------------
    def execute_block_end(self, line):
        # Lógica de fechamento de blocos (sem alteração)
        if self._in_class_block:
             if self._in_func_block: 
                 self._class_methods[self._func_name] = (self._func_params, self._func_block); self._in_func_block = False; self._func_block = []; return
             else: 
                 self.classes[self._class_name] = self._class_methods; self._in_class_block = False; self._class_methods = {}; return
        if self._in_func_block: 
            self.functions[self._func_name] = (self._func_params, self._func_block); self._in_func_block = False; self._func_block = []; return

        if self._in_now_block: self.process_try_block(); self._in_now_block = False; return
        if self._in_except_block: self._in_except_block = False;
        if self._in_try_block: self._in_try_block = False;
        
        if self._in_for_block: self.process_for_block(); self._in_for_block = False; return
        if self._in_while_block: self.process_while_block(); self._in_while_block = False; return
        if self._in_if_block: self.process_current_if_block(); self._in_if_block = False; return
        
        raise self.LineNoRecognized("'}' sem bloco ativo")

    def process_try_block(self):
        """ Processa o bloco Try/Except/Now, incluindo a captura do erro com 'as'. """
        try_block, except_block, now_block = self._try_block, self._except_block, self._now_block
        
        error_caught = None
        try: 
            self.execute_block(try_block)
        except self.TyrtRuntimeError as e: 
            error_caught = e
        except Exception as e: 
            # Erros Python não mapeados são tratados como exceções não TyrtLang.
            raise e
        
        # Se houve erro E existe bloco Except, executa o Except.
        if error_caught and except_block:
             try: 
                 # Atribui o objeto de erro à variável definida pelo usuário (via 'as')
                 self.variables[self._except_var_name] = error_caught
                 self.execute_block(except_block)
             except Exception as ex: 
                 raise ex
        
        # Executa o Now (Finally).
        if now_block:
            try: self.execute_block(now_block)
            except Exception as e: raise e
            
        self._try_block = []; self._except_block = []; self._now_block = []

    # Métodos process_for_block, process_while_block, process_current_if_block, execute_block, eval_condition
    # (sem alterações significativas)
    def process_for_block(self):
        start_val, end_val = int(self._for_start), int(self._for_end)
        for i in range(start_val, end_val + 1):
            self.variables[self._for_var] = i
            try: self.execute_block(self._for_block)
            except self.LoopBreakTyrt: break 
            except self.LoopContinueTyrt: continue 
        self._for_block = []

    def process_while_block(self):
        block = self._while_block
        while self.eval_condition(self._while_condition):
            try: self.execute_block(block)
            except self.LoopBreakTyrt: break 
            except self.LoopContinueTyrt: continue 
        self._while_condition = None; self._while_block = []

    def process_current_if_block(self):
          if self._current_if_is_active: self.execute_block(self._current_if_block_lines)
          self._current_if_is_active = False; self._current_if_block_lines = []
    
    def execute_block(self, lines, local_vars=None, instance=None):
        is_function_call = local_vars is not None
        old_variables = self.variables.copy()
        if is_function_call: self.variables = local_vars
        return_value = None
        
        try:
            for line in lines:
                if line.startswith("return_object"): 
                    return_value = self.eval_expr(line[len("return_object"):].strip(), self.variables, instance)
                    return return_value 
                self.execute_line(line, current_instance=instance)

        except Exception as e:
            if isinstance(e, (self.LoopBreakTyrt, self.LoopContinueTyrt, self.TyrtRuntimeError)): raise e
            if not isinstance(e, self.TyrtError): raise self.TyrtRuntimeError(f"Erro interno: {e.__class__.__name__}: {e}")
            raise e
        finally:
            if is_function_call: self.variables = old_variables
        
        return return_value

    def eval_condition(self, condition_expr):
        result = self.eval_expr(condition_expr)
        return bool(result)

    if __name__ == "__main__":
      TyrtLangInterpreter()
