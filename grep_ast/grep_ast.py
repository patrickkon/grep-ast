#!/usr/bin/env python

import re

from .dump import dump  # noqa: F401
from .parsers import filename_to_lang
from .tsl import get_parser


class TreeContext:
    def __init__(
        self,
        filename,
        code,
        color=False,
        verbose=False,
        line_number=False,
        parent_context=True,
        child_context=True,
        last_line=True,
        margin=3,
        mark_lois=True,
        header_max=10,
        show_top_of_file_parent_scope=True,
        loi_pad=1,
    ):
        self.filename = filename
        self.color = color
        self.verbose = verbose
        self.line_number = line_number
        self.last_line = last_line
        self.margin = margin
        self.mark_lois = mark_lois
        self.header_max = header_max
        self.loi_pad = loi_pad
        self.show_top_of_file_parent_scope = show_top_of_file_parent_scope

        self.parent_context = parent_context
        self.child_context = child_context

        lang = filename_to_lang(filename)
        if not lang:
            raise ValueError(f"Unknown language for {filename}")

        # Get parser based on file extension
        parser = get_parser(lang)
        tree = parser.parse(bytes(code, "utf8"))

        self.lines = code.splitlines()
        self.num_lines = len(self.lines) + 1

        # color lines, with highlighted matches
        self.output_lines = dict()

        # Which scopes is each line part of?
        # A scope is the line number on which the scope started
        self.scopes = [set() for _ in range(self.num_lines)]

        # Which lines serve as a short "header" for the scope starting on that line
        self.header = [list() for _ in range(self.num_lines)]

        self.nodes = [list() for _ in range(self.num_lines)]

        root_node = tree.root_node
        self.walk_tree(root_node)

        if self.verbose:
            scope_width = max(len(str(set(self.scopes[i]))) for i in range(self.num_lines - 1))
        for i in range(self.num_lines):
            header = sorted(self.header[i])
            if self.verbose and i < self.num_lines - 1:
                scopes = str(sorted(set(self.scopes[i])))
                print(f"{scopes.ljust(scope_width)}", i, self.lines[i])

            if len(header) > 0: # i changed this from 1 to 0, i think they have a bug..
                size, head_start, head_end = header[0]
                if size > self.header_max: # TODO: need to be careful here, since my class/functions/multi-line constructs may exceed the header_max ... since the default is only 10 lines
                    head_end = head_start + self.header_max
            else:
                head_start = i
                head_end = i + 1

            self.header[i] = head_start, head_end # we are setting the largest header for a particular start line i. This is set by header[0] above. 

        self.show_lines = set()
        self.lines_of_interest = set()

        # print(self.header)
        # for i in range(len(self.header)):
        #     print(i)
        #     print(self.header[i])
        # print(self.filename)
        with open("tree_sitter_header_output.txt", "a") as f:
            for i in range(len(self.header)):
                f.write(f"{i}\n")
                f.write(f"{self.header[i]}\n")
            f.write(f"{self.filename}\n")
        with open("tree_sitter_scope_output.txt", "a") as f:        
            for i in range(len(self.scopes)):
                f.write(f"{i}\n")
                f.write(f"{self.scopes[i]}\n")
            f.write(f"{self.filename}\n")
        with open("tree_sitter_node_output.txt", "a") as f:
            for i in range(len(self.nodes)):
                f.write(f"{i}\n")
                f.write(f"{self.nodes[i]}\n")
            f.write(f"{self.filename}\n")
        print(self.filename)
        # while True:
        #     x=1
        # print(self.scopes[8])
        # while True:
        #     x=1

        return

    def grep(self, pat, ignore_case):
        found = set()
        for i, line in enumerate(self.lines):
            if re.search(pat, line, re.IGNORECASE if ignore_case else 0):
                if self.color:
                    highlighted_line = re.sub(
                        pat,
                        lambda match: f"\033[1;31m{match.group()}\033[0m",  # noqa
                        line,
                        flags=re.IGNORECASE if ignore_case else 0,
                    )
                    self.output_lines[i] = highlighted_line
                found.add(i)
        return found

    def add_lines_of_interest(self, line_nums):
        self.lines_of_interest.update(line_nums)

    def add_context(self):
        if not self.lines_of_interest:
            return

        self.done_parent_scopes = set()

        self.show_lines = set(self.lines_of_interest)

        if self.loi_pad:
            for line in list(self.show_lines):
                for new_line in range(line - self.loi_pad, line + self.loi_pad + 1):
                    # if not self.scopes[line].intersection(self.scopes[new_line]):
                    #    continue
                    if new_line >= self.num_lines:
                        continue
                    if new_line < 0:
                        continue
                    self.show_lines.add(new_line)

        if self.last_line:
            # add the bottom line (plus parent context)
            bottom_line = self.num_lines - 2
            self.show_lines.add(bottom_line)
            self.add_parent_scopes(bottom_line)

        if self.parent_context:
            # For each line of interest, show all lines of the larger parent scope up till but excluding the root node (i.e., start of the file till end of file) [this is my current interpretation]
            # print(self.lines_of_interest)
            for i in set(self.lines_of_interest):
                self.add_parent_scopes(i)
            # print("me is dine")
            # print(self.show_lines)
            print("In grep_ast.py. Filename now: ", self.filename)
            # print("Show lines: ", self.show_lines)
            # while True:
            #     x=1

        if self.child_context:
            for i in set(self.lines_of_interest):
                self.add_child_context(i)

        # add the top margin lines of the file
        if self.margin:
            self.show_lines.update(range(self.margin))

        self.close_small_gaps()

    def add_child_context(self, i):
        if not self.nodes[i]:
            return

        last_line = self.get_last_line_of_scope(i)
        size = last_line - i
        if size < 5:
            self.show_lines.update(range(i, last_line + 1))
            return

        children = []
        for node in self.nodes[i]:
            children += self.find_all_children(node)

        children = sorted(
            children,
            key=lambda node: node.end_point[0] - node.start_point[0],
            reverse=True,
        )

        currently_showing = len(self.show_lines)
        max_to_show = 25
        min_to_show = 5
        percent_to_show = 0.10
        max_to_show = max(min(size * percent_to_show, max_to_show), min_to_show)

        for child in children:
            if len(self.show_lines) > currently_showing + max_to_show:
                break
            child_start_line = child.start_point[0]
            self.add_parent_scopes(child_start_line)

    def find_all_children(self, node):
        children = [node]
        for child in node.children:
            children += self.find_all_children(child)
        return children

    def get_last_line_of_scope(self, i):
        last_line = max(node.end_point[0] for node in self.nodes[i])
        return last_line

    def close_small_gaps(self):
        # a "closing" operation on the integers in set.
        # if i and i+2 are in there but i+1 is not, I want to add i+1
        # Create a new set for the "closed" lines
        closed_show = set(self.show_lines)
        sorted_show = sorted(self.show_lines)
        for i in range(len(sorted_show) - 1):
            if sorted_show[i + 1] - sorted_show[i] == 2:
                closed_show.add(sorted_show[i] + 1)

        # pick up adjacent blank lines
        for i, line in enumerate(self.lines):
            if i not in closed_show:
                continue
            if self.lines[i].strip() and i < self.num_lines - 2 and not self.lines[i + 1].strip():
                closed_show.add(i + 1)

        self.show_lines = closed_show

    def format(self):
        if not self.show_lines:
            return ""

        output = ""
        if self.color:
            # reset
            output += "\033[0m\n"

        dots = not (0 in self.show_lines)
        for i, line in enumerate(self.lines):
            if i not in self.show_lines:
                if dots:
                    if self.line_number:
                        output += "...⋮...\n"
                    else:
                        output += "⋮\n"
                    dots = False
                continue

            if i in self.lines_of_interest and self.mark_lois:
                spacer = "█"
                if self.color:
                    spacer = f"\033[31m{spacer}\033[0m"
            else:
                spacer = "│"

            line_output = f"{spacer}{self.output_lines.get(i, line)}"
            if self.line_number:
                line_output = f"{i + 1: 3}" + line_output
            output += line_output + "\n"

            dots = True

        return output

    def add_parent_scopes(self, i):
        if i in self.done_parent_scopes:
            return
        self.done_parent_scopes.add(i)

        if i >= len(self.scopes):
            return
        # print(self.scopes[i])
        # print(i)
        # while True:
        #     x=1
        for line_num in self.scopes[i]:
            head_start, head_end = self.header[line_num]
            if head_start > 0 or self.show_top_of_file_parent_scope:
                # print("me iss here: ", head_start, head_end)
                # print("me is god: ", range(head_start, head_end))
                self.show_lines.update(range(head_start, head_end))  # though head_end is not inclusive, we did head_end + 1 above such that the actual head_end is included

            if self.last_line:
                last_line = self.get_last_line_of_scope(line_num)
                self.add_parent_scopes(last_line)

    def walk_tree(self, node, depth=0):
        """
        This function is called recursively to traverse the AST.
        
        At the beginning, node is the root_node of the AST. This will recursively traverse all child nodes of the root_node. 

        self.scopes meaning: self.scopes[8] with the value {0, 8, 7} means in the context of the AST traversal.
            self.scopes[8] represents all the scopes that line 8 is contained within. The set {0, 8, 7} means that line 8 is contained within three different scopes that start at:
            Line 0 (typically the file/module scope)
            Line 7 (a scope that started one line before)
            Line 8 (its own scope)

        In walk_tree, we will be adding 0 8 7 iteratively into the self.scopes[8] set. This is possible because each line contained within the current node will be used to updated the self.scopes set. That is, if line 8 is within node, then self.scopes[8] will be added with the starting_line of the node (where for the root node this will be 0). 

        """
        # print(node.type)
        # while True:
        #     x=1

        #Gets the start and end points of the node. In tree-sitter, each node has position information in the form of (line, column) tuples
        start = node.start_point
        end = node.end_point

        with open("tree_sitter_output.txt", "a") as f:
            f.write(f"Start: {start}, End: {end}\n")
            f.write(f"Node type: {node.type}\n")
            f.write(f"Node text: {node.text}\n")

        start_line = start[0]
        end_line = end[0]
        size = end_line - start_line

        self.nodes[start_line].append(node) # self.nodes is a list of lists, where self.nodes[i] contains all AST nodes that begin on line i

        # dump(start_line, end_line, node.text)
        if self.verbose and node.is_named:
            """
            for k in dir(node):
                print(k, getattr(node, k))
            """
            print(
                "   " * depth,
                node.type,
                f"{start_line}-{end_line}={size + 1}",
                node.text.splitlines()[0],
                self.lines[start_line],
            )

        if size:
            """
            If the node spans multiple lines (size >= 1, ACTUAL SIZE >= 2) Actual size should be size + 1, i.e., if size = 1, there are actually 2 lines. This is why you see many nodes not having a header, since this is heuristic designed to capture say functions.
            Adds a tuple of (size, start_line, end_line) to self.header[start_line]
            This tracks "header" lines that begin multi-line constructs (like function definitions)
            """
            self.header[start_line].append((size, start_line, end_line))

        for i in range(start_line, end_line + 1):
            """
            For each line in the node's range
            Adds the start_line to that line's set of scopes
            This builds a mapping of which lines are contained within which scopes
            """
            self.scopes[i].add(start_line)

        for child in node.children:
            self.walk_tree(child, depth + 1)
        # print(self.scopes[8])
        # while True:
        #     x=1
        return start_line, end_line
