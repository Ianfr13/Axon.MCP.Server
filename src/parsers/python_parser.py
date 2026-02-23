import tree_sitter
import tree_sitter_python
import re
from typing import List, Optional, Dict, Any
from pathlib import Path
from src.config.enums import LanguageEnum, SymbolKindEnum, AccessModifierEnum
from src.parsers.tree_sitter_parser import TreeSitterParser
from src.parsers.base_parser import ParsedSymbol


class PythonParser(TreeSitterParser):
    """Python language parser using Tree-sitter."""

    def __init__(self):
        super().__init__(LanguageEnum.PYTHON, tree_sitter_python)

    def is_supported(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == '.py'

    def _extract_symbols(self, node: tree_sitter.Node, code: str) -> List[ParsedSymbol]:
        symbols = []

        def traverse(n: tree_sitter.Node, parent_name: Optional[str] = None):
            if n.type == 'function_definition':
                symbol = self._parse_function(n, code, parent_name)
                symbols.append(symbol)

            elif n.type == 'class_definition':
                symbol = self._parse_class(n, code, parent_name)
                symbols.append(symbol)
                class_name = symbol.fully_qualified_name
                # Traverse class body for methods
                body = self._find_child_by_type(n, 'block')
                if body:
                    for child in body.children:
                        traverse(child, class_name)
                return  # Don't re-traverse children

            elif n.type == 'decorated_definition':
                # Handle decorated functions/classes
                for child in n.children:
                    if child.type in ('function_definition', 'class_definition'):
                        traverse(child, parent_name)
                return

            for child in n.children:
                traverse(child, parent_name)

        traverse(node)
        return symbols

    def _parse_function(self, node: tree_sitter.Node, code: str, parent_name: Optional[str]) -> ParsedSymbol:
        name_node = self._find_child_by_type(node, 'identifier')
        name = self._get_node_text(name_node, code) if name_node else "anonymous"

        parameters = self._extract_parameters(node, code)
        return_type = self._extract_return_type(node, code)
        docstring = self._extract_docstring(node, code)
        decorators = self._extract_decorators(node, code)

        # Determine kind and access
        is_method = parent_name is not None
        kind = SymbolKindEnum.METHOD if is_method else SymbolKindEnum.FUNCTION
        access = None
        if name.startswith('__') and name.endswith('__'):
            access = AccessModifierEnum.PUBLIC  # dunder methods
        elif name.startswith('__'):
            access = AccessModifierEnum.PRIVATE
        elif name.startswith('_'):
            access = AccessModifierEnum.PROTECTED

        # Check for property decorator
        if any(d == '@property' for d in decorators):
            kind = SymbolKindEnum.PROPERTY

        # Check for staticmethod/classmethod
        structured_docs = None
        if docstring:
            structured_docs = self._parse_docstring(docstring)
        if decorators:
            if structured_docs is None:
                structured_docs = {}
            structured_docs['decorators'] = decorators

        # Build signature
        signature = self._get_function_signature(node, code)

        # Check for FastAPI/Flask endpoint decorators
        endpoint_info = self._extract_endpoint_info(decorators)
        if endpoint_info:
            kind = SymbolKindEnum.ENDPOINT
            if structured_docs is None:
                structured_docs = {}
            structured_docs['endpoint'] = endpoint_info

        return ParsedSymbol(
            kind=kind,
            name=name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            start_column=node.start_point[1],
            end_column=node.end_point[1],
            signature=signature,
            documentation=docstring,
            structured_docs=structured_docs,
            parameters=parameters,
            return_type=return_type,
            access_modifier=access,
            parent_name=parent_name,
            fully_qualified_name=f"{parent_name}.{name}" if parent_name else name,
        )

    def _parse_class(self, node: tree_sitter.Node, code: str, parent_name: Optional[str]) -> ParsedSymbol:
        name_node = self._find_child_by_type(node, 'identifier')
        name = self._get_node_text(name_node, code) if name_node else "AnonymousClass"

        docstring = self._extract_docstring(node, code)
        decorators = self._extract_decorators(node, code)
        bases = self._extract_bases(node, code)

        node_text = self._get_node_text(node, code)
        signature = node_text.split(':')[0].strip() if ':' in node_text else node_text[:200]

        structured_docs = None
        if docstring:
            structured_docs = self._parse_docstring(docstring)
        if decorators:
            if structured_docs is None:
                structured_docs = {}
            structured_docs['decorators'] = decorators
        if bases:
            if structured_docs is None:
                structured_docs = {}
            structured_docs['bases'] = bases

        return ParsedSymbol(
            kind=SymbolKindEnum.CLASS,
            name=name,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            start_column=node.start_point[1],
            end_column=node.end_point[1],
            signature=signature,
            documentation=docstring,
            structured_docs=structured_docs,
            parent_name=parent_name,
            fully_qualified_name=f"{parent_name}.{name}" if parent_name else name,
        )

    def _extract_parameters(self, node: tree_sitter.Node, code: str) -> List[dict]:
        parameters = []
        params_node = self._find_child_by_type(node, 'parameters')
        if not params_node:
            return parameters

        for child in params_node.children:
            if child.type == 'identifier':
                name = self._get_node_text(child, code)
                if name != 'self' and name != 'cls':
                    parameters.append({'name': name, 'type': None})

            elif child.type == 'typed_parameter':
                param_name = None
                param_type = None
                for sub in child.children:
                    if sub.type == 'identifier' and param_name is None:
                        param_name = self._get_node_text(sub, code)
                    elif sub.type == 'type':
                        param_type = self._get_node_text(sub, code)
                if param_name and param_name not in ('self', 'cls'):
                    parameters.append({'name': param_name, 'type': param_type})

            elif child.type == 'default_parameter':
                param_name = None
                for sub in child.children:
                    if sub.type == 'identifier' and param_name is None:
                        param_name = self._get_node_text(sub, code)
                        break
                if param_name and param_name not in ('self', 'cls'):
                    parameters.append({'name': param_name, 'type': None})

            elif child.type == 'typed_default_parameter':
                param_name = None
                param_type = None
                for sub in child.children:
                    if sub.type == 'identifier' and param_name is None:
                        param_name = self._get_node_text(sub, code)
                    elif sub.type == 'type':
                        param_type = self._get_node_text(sub, code)
                if param_name and param_name not in ('self', 'cls'):
                    parameters.append({'name': param_name, 'type': param_type})

            elif child.type == 'list_splat_pattern':
                name = self._get_node_text(child, code)
                parameters.append({'name': name, 'type': None})

            elif child.type == 'dictionary_splat_pattern':
                name = self._get_node_text(child, code)
                parameters.append({'name': name, 'type': None})

        return parameters

    def _extract_return_type(self, node: tree_sitter.Node, code: str) -> Optional[str]:
        ret_type = self._find_child_by_type(node, 'type')
        if ret_type:
            return self._get_node_text(ret_type, code)
        return None

    def _extract_docstring(self, node: tree_sitter.Node, code: str) -> Optional[str]:
        """Extract docstring from function or class body."""
        body = self._find_child_by_type(node, 'block')
        if not body or not body.children:
            return None

        first_stmt = None
        for child in body.children:
            if child.type not in ('comment', 'newline'):
                first_stmt = child
                break

        if not first_stmt:
            return None

        if first_stmt.type == 'expression_statement':
            expr = first_stmt.children[0] if first_stmt.children else None
            if expr and expr.type == 'string':
                raw = self._get_node_text(expr, code)
                # Strip triple quotes
                if raw.startswith('"""') or raw.startswith("'''"):
                    return raw[3:-3].strip()
                elif raw.startswith('"') or raw.startswith("'"):
                    return raw[1:-1].strip()

        return None

    def _extract_decorators(self, node: tree_sitter.Node, code: str) -> List[str]:
        """Extract decorators from parent decorated_definition or preceding siblings."""
        decorators = []

        # Check if parent is decorated_definition
        parent = node.parent
        if parent and parent.type == 'decorated_definition':
            for child in parent.children:
                if child.type == 'decorator':
                    decorators.append(self._get_node_text(child, code))

        return decorators

    def _extract_bases(self, node: tree_sitter.Node, code: str) -> List[str]:
        """Extract base classes from class definition."""
        bases = []
        arg_list = self._find_child_by_type(node, 'argument_list')
        if arg_list:
            for child in arg_list.children:
                if child.type not in ('(', ')', ','):
                    bases.append(self._get_node_text(child, code))
        return bases

    def _get_function_signature(self, node: tree_sitter.Node, code: str) -> str:
        text = self._get_node_text(node, code)
        # Extract up to the colon that starts the body
        if ':' in text:
            # Find the colon after parameters (not in type annotations)
            paren_depth = 0
            bracket_depth = 0
            for i, ch in enumerate(text):
                if ch == '(':
                    paren_depth += 1
                elif ch == ')':
                    paren_depth -= 1
                elif ch == '[':
                    bracket_depth += 1
                elif ch == ']':
                    bracket_depth -= 1
                elif ch == ':' and paren_depth == 0 and bracket_depth == 0:
                    return text[:i].strip()
        return text[:200]

    def _parse_docstring(self, docstring: str) -> Optional[Dict[str, Any]]:
        """Parse Google/Numpy/Sphinx style docstring."""
        result = {}

        # Extract description (first paragraph before any section)
        lines = docstring.split('\n')
        desc_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.lower().startswith(('args:', 'arguments:', 'parameters:', 'params:',
                                           'returns:', 'return:', 'raises:', 'raise:',
                                           'yields:', 'yield:', 'note:', 'notes:',
                                           'example:', 'examples:', 'todo:',
                                           ':param', ':type', ':returns', ':rtype', ':raises')):
                break
            desc_lines.append(stripped)

        desc = ' '.join(desc_lines).strip()
        if desc:
            result['description'] = desc

        # Extract params (Google style)
        param_section = re.search(
            r'(?:Args|Arguments|Parameters|Params):\s*\n(.*?)(?=\n\s*(?:Returns|Raises|Yields|Note|Example|Todo):|$)',
            docstring, re.DOTALL | re.IGNORECASE
        )
        if param_section:
            param_text = param_section.group(1)
            params = re.findall(r'(\w+)\s*(?:\(([^)]*)\))?\s*:\s*(.*?)(?=\n\s*\w|\Z)', param_text, re.DOTALL)
            if params:
                result['params'] = [
                    {'name': name, 'type': ptype if ptype else None, 'description': desc.strip()}
                    for name, ptype, desc in params
                ]

        # Extract Sphinx-style params (:param name: desc)
        sphinx_params = re.findall(r':param\s+(?:(\w+)\s+)?(\w+):\s*(.*?)(?=\n\s*:|$)', docstring, re.DOTALL)
        if sphinx_params and 'params' not in result:
            result['params'] = [
                {'name': name, 'type': ptype if ptype else None, 'description': desc.strip()}
                for ptype, name, desc in sphinx_params
            ]

        # Extract returns
        returns_match = re.search(
            r'(?:Returns|Return):\s*\n?\s*(.*?)(?=\n\s*(?:Raises|Yields|Note|Example|Todo):|$)',
            docstring, re.DOTALL | re.IGNORECASE
        )
        if returns_match:
            result['returns'] = {'description': returns_match.group(1).strip()}

        # Extract raises
        raises_match = re.search(
            r'(?:Raises|Raise):\s*\n(.*?)(?=\n\s*(?:Returns|Yields|Note|Example|Todo):|$)',
            docstring, re.DOTALL | re.IGNORECASE
        )
        if raises_match:
            raises_text = raises_match.group(1)
            raises = re.findall(r'(\w+)\s*:\s*(.*?)(?=\n\s*\w|\Z)', raises_text, re.DOTALL)
            if raises:
                result['throws'] = [
                    {'type': exc_type, 'description': desc.strip()}
                    for exc_type, desc in raises
                ]

        return result if result else None

    def _extract_endpoint_info(self, decorators: List[str]) -> Optional[Dict[str, Any]]:
        """Extract FastAPI/Flask endpoint info from decorators."""
        for dec in decorators:
            # FastAPI: @app.get("/path"), @router.post("/path")
            match = re.match(
                r'@\w+\.(get|post|put|delete|patch|head|options)\s*\(\s*["\']([^"\']*)["\']',
                dec, re.IGNORECASE
            )
            if match:
                return {
                    'http_method': match.group(1).upper(),
                    'path': match.group(2),
                    'framework': 'fastapi',
                }

            # Flask: @app.route("/path", methods=["GET"])
            route_match = re.match(
                r'@\w+\.route\s*\(\s*["\']([^"\']*)["\']',
                dec, re.IGNORECASE
            )
            if route_match:
                method = 'GET'
                method_match = re.search(r'methods\s*=\s*\[([^\]]+)\]', dec)
                if method_match:
                    method = method_match.group(1).strip().strip('"\'').upper()
                return {
                    'http_method': method,
                    'path': route_match.group(1),
                    'framework': 'flask',
                }

        return None

    def _extract_imports(self, node: tree_sitter.Node, code: str) -> List[str]:
        imports = []

        def traverse(n: tree_sitter.Node):
            if n.type == 'import_statement':
                # import foo, import foo.bar
                for child in n.children:
                    if child.type == 'dotted_name':
                        imports.append(self._get_node_text(child, code))
                    elif child.type == 'aliased_import':
                        name_node = self._find_child_by_type(child, 'dotted_name')
                        if name_node:
                            imports.append(self._get_node_text(name_node, code))

            elif n.type == 'import_from_statement':
                # from foo import bar
                module = None
                for child in n.children:
                    if child.type == 'dotted_name':
                        module = self._get_node_text(child, code)
                        break
                    elif child.type == 'relative_import':
                        module = self._get_node_text(child, code)
                        break
                if module:
                    imports.append(module)

            for child in n.children:
                traverse(child)

        traverse(node)
        return imports

    def _extract_exports(self, node: tree_sitter.Node, code: str) -> List[str]:
        """Extract __all__ exports."""
        exports = []

        def traverse(n: tree_sitter.Node):
            if n.type == 'expression_statement':
                child = n.children[0] if n.children else None
                if child and child.type == 'assignment':
                    left = child.children[0] if child.children else None
                    if left and self._get_node_text(left, code) == '__all__':
                        right = child.children[-1] if len(child.children) > 2 else None
                        if right and right.type == 'list':
                            for item in right.children:
                                if item.type == 'string':
                                    text = self._get_node_text(item, code).strip('"\'')
                                    exports.append(text)

            for child in n.children:
                traverse(child)

        traverse(node)
        return exports
