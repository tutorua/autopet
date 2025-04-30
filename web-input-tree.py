import sys
import asyncio
from PyQt6.QtWidgets import (QApplication, QMainWindow, QSplitter, QTreeView, 
                             QTextEdit, QListWidget, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QToolBar, QStatusBar, QLineEdit, QPushButton,
                             QMessageBox)
from PyQt6.QtCore import Qt, QSize, QModelIndex, QAbstractItemModel, pyqtSignal, QThread
from PyQt6.QtGui import QAction, QStandardItemModel, QStandardItem, QIcon

# Import Playwright
from playwright.async_api import async_playwright

class WebElementTreeItem:
    def __init__(self, data, parent=None):
        self.parent_item = parent
        self.item_data = data
        self.child_items = []
        
        # Element properties
        self.element_id = data.get('id', '')
        self.element_tag = data.get('tag', '')
        self.element_type = data.get('type', '')
        self.element_value = data.get('value', '')
        self.element_name = data.get('name', '')
        self.element_xpath = data.get('xpath', '')
        self.element_css = data.get('css', '')
        
    def appendChild(self, item):
        self.child_items.append(item)
        
    def child(self, row):
        if row < 0 or row >= len(self.child_items):
            return None
        return self.child_items[row]
        
    def childCount(self):
        return len(self.child_items)
        
    def columnCount(self):
        return 1
        
    def data(self, column):
        if column == 0:
            display_text = self.element_tag
            if self.element_id:
                display_text += f" (id={self.element_id})"
            elif self.element_name:
                display_text += f" (name={self.element_name})"
            return display_text
        return None
        
    def parent(self):
        return self.parent_item
        
    def row(self):
        if self.parent_item:
            return self.parent_item.child_items.index(self)
        return 0


class WebElementTreeModel(QAbstractItemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.root_item = WebElementTreeItem({"tag": "Document"})
        
    def index(self, row, column, parent=QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
            
        if not parent.isValid():
            parent_item = self.root_item
        else:
            parent_item = parent.internalPointer()
            
        child_item = parent_item.child(row)
        if child_item:
            return self.createIndex(row, column, child_item)
        return QModelIndex()
        
    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
            
        child_item = index.internalPointer()
        parent_item = child_item.parent()
        
        if parent_item == self.root_item:
            return QModelIndex()
            
        return self.createIndex(parent_item.row(), 0, parent_item)
        
    def rowCount(self, parent=QModelIndex()):
        if parent.column() > 0:
            return 0
            
        if not parent.isValid():
            parent_item = self.root_item
        else:
            parent_item = parent.internalPointer()
            
        return parent_item.childCount()
        
    def columnCount(self, parent=QModelIndex()):
        return 1
        
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
            
        if role != Qt.ItemDataRole.DisplayRole:
            return None
            
        item = index.internalPointer()
        return item.data(index.column())
        
    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return "Web Elements"
        return None
        
    def addWebElements(self, elements_data, parent_index=QModelIndex()):
        if not parent_index.isValid():
            parent_item = self.root_item
        else:
            parent_item = parent_index.internalPointer()
            
        for element_data in elements_data:
            item = WebElementTreeItem(element_data, parent_item)
            parent_item.appendChild(item)
            
            # Add children if they exist
            if 'children' in element_data and element_data['children']:
                last_row = parent_item.childCount() - 1
                new_parent_index = self.index(last_row, 0, parent_index)
                self.addWebElements(element_data['children'], new_parent_index)
                
    def clearElements(self):
        self.beginResetModel()
        self.root_item = WebElementTreeItem({"tag": "Document"})
        self.endResetModel()
        
    def populateTree(self, elements_data):
        self.beginResetModel()
        self.clearElements()
        self.addWebElements(elements_data)
        self.endResetModel()


class PlaywrightWorker(QThread):
    """Worker thread for Playwright operations to keep UI responsive"""
    finished = pyqtSignal(list, str)
    error = pyqtSignal(str)
    
    def __init__(self, url):
        super().__init__()
        self.url = url
        
    def run(self):
        try:
            # Create event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Run the extraction task
            elements = loop.run_until_complete(self.extract_elements())
            
            # Signal completion with elements
            self.finished.emit(elements, self.url)
            
        except Exception as e:
            self.error.emit(str(e))
    
    async def extract_elements(self):
        """Extract elements from web page using Playwright"""
        elements = []
        
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            
            # Navigate to the URL
            await page.goto(self.url)
            
            # Extract element data using JavaScript evaluation
            elements = await page.evaluate("""() => {
                function processElement(element) {
                    if (!element) return null;
                    
                    // Get basic element data
                    const result = {
                        tag: element.tagName.toLowerCase(),
                        id: element.id || '',
                        name: element.getAttribute('name') || '',
                        type: element.getAttribute('type') || '',
                        value: element.value || element.textContent || '',
                        xpath: getXPath(element),
                        css: getCssSelector(element),
                        children: []
                    };
                    
                    // Process children if any
                    for (const child of element.children) {
                        const childData = processElement(child);
                        if (childData) {
                            result.children.push(childData);
                        }
                    }
                    
                    return result;
                }
                
                // Helper function to get XPath
                function getXPath(element) {
                    if (!element) return '';
                    
                    if (element === document.body) return '/html/body';
                    
                    let ix = 0;
                    let siblings = element.parentNode?.children || [];
                    
                    for (let i = 0; i < siblings.length; i++) {
                        let sibling = siblings[i];
                        if (sibling === element) {
                            let path = getXPath(element.parentNode);
                            let tag = element.tagName.toLowerCase();
                            let pos = ix + 1;
                            
                            if (element.id) {
                                return `${path}//${tag}[@id="${element.id}"]`;
                            } else {
                                return `${path}/${tag}[${pos}]`;
                            }
                        }
                        
                        if (sibling.nodeType === 1 && sibling.tagName === element.tagName) {
                            ix++;
                        }
                    }
                    
                    return '';
                }
                
                // Helper function to get CSS selector
                function getCssSelector(element) {
                    if (!element) return '';
                    if (element.id) return `#${element.id}`;
                    
                    let path = [];
                    while (element.nodeType === Node.ELEMENT_NODE) {
                        let selector = element.tagName.toLowerCase();
                        
                        if (element.id) {
                            selector += `#${element.id}`;
                            path.unshift(selector);
                            break;
                        } else {
                            let sib = element, nth = 1;
                            while (sib = sib.previousElementSibling) {
                                if (sib.tagName.toLowerCase() === selector) nth++;
                            }
                            if (nth !== 1) selector += `:nth-of-type(${nth})`;
                        }
                        
                        path.unshift(selector);
                        element = element.parentNode;
                    }
                    
                    return path.join(' > ');
                }
                
                // Start processing from document element
                return [processElement(document.documentElement)];
            }""")
            
            await browser.close()
            return elements


class WebTestingTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Web Testing Tool")
        self.resize(1200, 800)
        
        # Create status bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready")
        
        # Main layout
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        self.setCentralWidget(main_widget)
        
        # URL bar
        url_widget = QWidget()
        url_layout = QHBoxLayout(url_widget)
        url_layout.setContentsMargins(0, 0, 0, 0)
        
        url_label = QLabel("URL:")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter website URL (e.g., https://example.com)")
        self.url_input.returnPressed.connect(self.load_url)
        
        load_button = QPushButton("Load Page")
        load_button.clicked.connect(self.load_url)
        
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input, 1)
        url_layout.addWidget(load_button)
        
        main_layout.addWidget(url_widget)
        
        # Create central widget with splitter
        self.central_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.central_splitter, 1)  # Give it stretch factor
        
        # Left pane - Web Elements Tree
        self.left_pane = QWidget()
        left_layout = QVBoxLayout(self.left_pane)
        left_layout.setContentsMargins(2, 2, 2, 2)
        
        # Label for left pane
        left_label = QLabel("Web Elements")
        left_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(left_label)
        
        # Tree view for web elements
        self.element_tree = QTreeView()
        self.element_tree.setHeaderHidden(False)
        self.element_tree.setAnimated(True)
        self.element_tree.setAlternatingRowColors(True)
        left_layout.addWidget(self.element_tree)
        
        # Set up the model for the tree view
        self.element_model = WebElementTreeModel()
        self.element_tree.setModel(self.element_model)
        
        # Connect signals
        self.element_tree.clicked.connect(self.on_element_clicked)
        
        # Add left pane to splitter
        self.central_splitter.addWidget(self.left_pane)
        
        # Central pane - Test Code Editor
        self.central_pane = QWidget()
        central_layout = QVBoxLayout(self.central_pane)
        central_layout.setContentsMargins(2, 2, 2, 2)
        
        # Label for central pane
        central_label = QLabel("Test Code")
        central_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        central_layout.addWidget(central_label)
        
        # Text editor for code
        self.code_editor = QTextEdit()
        central_layout.addWidget(self.code_editor)
        
        # Add central pane to splitter
        self.central_splitter.addWidget(self.central_pane)
        
        # Right pane - Assertions List
        self.right_pane = QWidget()
        right_layout = QVBoxLayout(self.right_pane)
        right_layout.setContentsMargins(2, 2, 2, 2)
        
        # Label for right pane
        right_label = QLabel("Test Assertions")
        right_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(right_label)
        
        # List widget for assertions
        self.assertion_list = QListWidget()
        right_layout.addWidget(self.assertion_list)
        
        # Add right pane to splitter
        self.central_splitter.addWidget(self.right_pane)
        
        # Set initial sizes for the panes (30% - 40% - 30%)
        self.central_splitter.setSizes([360, 480, 360])
        
        # Initialize Playwright worker
        self.playwright_worker = None
        
        # Default URL
        self.url_input.setText("https://example.com")
        
    def on_element_clicked(self, index):
        item = index.internalPointer()
        if item:
            element_info = (
                f"Tag: {item.element_tag}\n"
                f"ID: {item.element_id}\n"
                f"Name: {item.element_name}\n"
                f"Type: {item.element_type}\n"
                f"Value: {item.element_value}\n"
                f"XPath: {item.element_xpath}\n"
                f"CSS Selector: {item.element_css}"
            )
            self.statusBar.showMessage(f"Selected: {item.data(0)}")
            
            # Generate test code when clicking elements
            self.generate_test_code(item)
            
    def generate_test_code(self, item):
        """Generate test code for the selected element"""
        if not item:
            return
            
        # Determine the best selector to use
        selector = ""
        if item.element_id:
            selector = f"id={item.element_id}"
        elif item.element_name:
            selector = f"name={item.element_name}"
        elif item.element_xpath:
            selector = f"xpath={item.element_xpath}"
        elif item.element_css:
            selector = f"css={item.element_css}"
        else:
            return  # No good selector available
            
        # Generate code based on element type
        code = ""
        if item.element_tag == "input":
            if item.element_type == "text" or item.element_type == "password":
                code = f"# Fill {item.element_tag} field\n"
                code += f"await page.fill('{selector}', 'test_value')\n"
            elif item.element_type == "checkbox" or item.element_type == "radio":
                code = f"# Check {item.element_tag}\n"
                code += f"await page.check('{selector}')\n"
        elif item.element_tag == "button" or item.element_tag == "a":
            code = f"# Click {item.element_tag}\n"
            code += f"await page.click('{selector}')\n"
        elif item.element_tag == "select":
            code = f"# Select option from dropdown\n"
            code += f"await page.select_option('{selector}', 'option_value')\n"
        else:
            code = f"# Interact with {item.element_tag}\n"
            code += f"await page.click('{selector}')\n"
            
        # Add code to editor
        current_code = self.code_editor.toPlainText()
        if current_code:
            current_code += "\n"
        self.code_editor.setText(current_code + code)
            
    def load_url(self):
        """Load a web page and extract its elements"""
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Input Error", "Please enter a valid URL")
            return
            
        # Add http if missing
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
            self.url_input.setText(url)
            
        # Update status
        self.statusBar.showMessage(f"Loading {url}...")
        
        # Disable UI while loading
        self.url_input.setEnabled(False)
        
        # Create and start worker thread
        self.playwright_worker = PlaywrightWorker(url)
        self.playwright_worker.finished.connect(self.on_page_loaded)
        self.playwright_worker.error.connect(self.on_load_error)
        self.playwright_worker.start()
        
    def on_page_loaded(self, elements, url):
        """Handle successful page load"""
        self.element_model.populateTree(elements)
        self.element_tree.expandToDepth(1)  # Expand first level
        self.statusBar.showMessage(f"Loaded {url} successfully")
        self.url_input.setEnabled(True)
        
        # Generate initial test setup code
        setup_code = f"# Test for {url}\n"
        setup_code += "from playwright.sync_api import sync_playwright\n\n"
        setup_code += "def run(playwright):\n"
        setup_code += "    browser = playwright.chromium.launch(headless=False)\n"
        setup_code += "    context = browser.new_context()\n"
        setup_code += "    page = context.new_page()\n\n"
        setup_code += f"    # Navigate to URL\n"
        setup_code += f"    page.goto('{url}')\n\n"
        setup_code += "    # Add your test steps here\n\n"
        setup_code += "    # Close browser\n"
        setup_code += "    browser.close()\n\n"
        setup_code += "with sync_playwright() as playwright:\n"
        setup_code += "    run(playwright)"
        
        self.code_editor.setText(setup_code)
        
    def on_load_error(self, error_message):
        """Handle page load error"""
        QMessageBox.critical(self, "Error Loading Page", f"Failed to load page: {error_message}")
        self.statusBar.showMessage("Error loading page")
        self.url_input.setEnabled(True)


def main():
    app = QApplication(sys.argv)
    window = WebTestingTool()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
    