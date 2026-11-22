"""Árbol de categorías en memoria (la tabla es pequeña: cientos de filas)."""
from __future__ import annotations

from collections import defaultdict

from .models import Categoria


class ArbolCategorias:
    def __init__(self, categorias: list[Categoria]):
        self.por_id: dict[str, Categoria] = {c.id_categoria: c for c in categorias}
        self.hijos: dict[str | None, list[Categoria]] = defaultdict(list)
        for c in sorted(categorias, key=lambda c: c.nombre.lower()):
            padre = c.id_categoria_padre if c.id_categoria_padre in self.por_id else None
            self.hijos[padre].append(c)

    def __len__(self) -> int:
        return len(self.por_id)

    def raices(self) -> list[Categoria]:
        return list(self.hijos.get(None, []))

    def hijos_de(self, id_categoria: str) -> list[Categoria]:
        return list(self.hijos.get(id_categoria, []))

    def descendientes(self, id_categoria: str) -> list[str]:
        """Incluye la propia categoría. Protegido contra ciclos."""
        if id_categoria not in self.por_id:
            return [id_categoria]
        resultado, visto, pila = [], set(), [id_categoria]
        while pila:
            actual = pila.pop()
            if actual in visto:
                continue
            visto.add(actual)
            resultado.append(actual)
            pila.extend(h.id_categoria for h in self.hijos.get(actual, []))
        return resultado

    def ruta(self, id_categoria: str | None) -> list[Categoria]:
        cadena, visto = [], set()
        while id_categoria and id_categoria in self.por_id and id_categoria not in visto:
            visto.add(id_categoria)
            cat = self.por_id[id_categoria]
            cadena.append(cat)
            id_categoria = cat.id_categoria_padre
        return list(reversed(cadena))

    def ruta_texto(self, id_categoria: str | None, sep: str = " › ") -> str:
        return sep.join(c.nombre for c in self.ruta(id_categoria)) or "—"

    def nombre(self, id_categoria: str | None) -> str:
        cat = self.por_id.get(id_categoria or "")
        return cat.nombre if cat else "—"

    def ordenadas_por_ruta(self) -> list[Categoria]:
        """Todas las categorías, recorridas en profundidad (para listas desplegables)."""
        salida: list[Categoria] = []

        def visitar(lista: list[Categoria]):
            for c in lista:
                salida.append(c)
                visitar(self.hijos.get(c.id_categoria, []))

        visitar(self.raices())
        return salida
